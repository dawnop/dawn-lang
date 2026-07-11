package dawn.check

import dawn.ast.*

/**
 * Pattern exhaustiveness via the classic usefulness algorithm (Maranget,
 * "Warnings for pattern matching", 2007). A match is exhaustive iff a wildcard
 * row is NOT useful after all its unguarded rows. Missing ADT constructors are
 * found by probing each constructor with wildcard arguments.
 */

internal sealed class SPat
internal object SWild : SPat()
internal class SCtor(val ctor: CtorInfo, val subs: List<SPat>) : SPat()
internal class SLit(val value: Any) : SPat()
internal class STuple(val subs: List<SPat>) : SPat()
internal class SList(val pre: List<SPat>, val hasRest: Boolean, val post: List<SPat>) : SPat() {
    val arity get() = pre.size + post.size
}

/** Lower an AST pattern; broken patterns become wildcards (errors were already reported). */
internal fun toSPat(p: Pattern): SPat = when (p) {
    is WildPat, is BindPat -> SWild
    is LitPat -> when (val l = p.lit) {
        is IntLit -> SLit(l.value)
        is FloatLit -> SLit(l.value)
        is BoolLit -> SLit(l.value)
        is StrLit -> SLit(l.parts.joinToString("") { (it as StrPart.Text).value })
        else -> SWild
    }
    is CtorPat -> {
        val ci = p.ctor
        val fps = p.fieldPats
        if (ci == null || fps == null) SWild
        else SCtor(ci, fps.map { if (it == null) SWild else toSPat(it) })
    }
    is TuplePat -> STuple(p.elems.map { toSPat(it) })
    is ListPat -> SList(p.pre.map { toSPat(it) }, p.hasRest, p.post.map { toSPat(it) })
}

/** Constructor field types with the column's type arguments substituted in. */
private fun instFields(c: CtorInfo, column: Type): List<Type> =
    if (column is Type.TAdt && c.adt.typeParams.isNotEmpty())
        c.fields.map { subst(it.type, c.adt.typeParams.zip(column.args).toMap()) }
    else c.fields.map { it.type }

/** Would a value matching [q] slip through every row of [matrix]? */
internal fun useful(matrix: List<List<SPat>>, q: List<SPat>, types: List<Type>): Boolean {
    if (q.isEmpty()) return matrix.isEmpty()
    val t = types.first()
    return when (val head = q.first()) {
        is SCtor -> useful(
            specializeCtor(matrix, head.ctor),
            head.subs + q.drop(1),
            instFields(head.ctor, t) + types.drop(1),
        )
        is SLit -> useful(specializeLit(matrix, head.value), q.drop(1), types.drop(1))
        is STuple -> useful(
            specializeTuple(matrix, head.subs.size),
            head.subs + q.drop(1),
            (t as? Type.TTuple)?.elems.orEmpty().ifEmpty { List(head.subs.size) { Type.TError } } + types.drop(1),
        )
        is SList -> {
            val elem = (t as? Type.TList)?.elem ?: Type.TError
            if (!head.hasRest) {
                val n = head.pre.size
                useful(specializeList(matrix, n), head.pre + q.drop(1), List(n) { elem } + types.drop(1))
            } else {
                // a rest pattern covers every length ≥ its arity; behaviour is
                // uniform beyond the longest pattern in play, so a finite probe suffices
                (head.arity..listLenBound(matrix, head)).any { len ->
                    useful(
                        specializeList(matrix, len),
                        head.pre + List(len - head.arity) { SWild } + head.post + q.drop(1),
                        List(len) { elem } + types.drop(1),
                    )
                }
            }
        }
        is SWild -> {
            // lists: probe every relevant length (same uniformity argument as above)
            if (t is Type.TList) {
                val bound = listLenBound(matrix, null)
                return (0..bound).any { len ->
                    useful(
                        specializeList(matrix, len),
                        List(len) { SWild } + q.drop(1),
                        List(len) { t.elem } + types.drop(1),
                    )
                }
            }
            // a tuple is its own single complete constructor
            if (t is Type.TTuple) {
                return useful(
                    specializeTuple(matrix, t.elems.size),
                    List(t.elems.size) { SWild } + q.drop(1),
                    t.elems + types.drop(1),
                )
            }
            // if the matrix heads form a complete signature, a wildcard is useful
            // iff it is useful under some constructor; otherwise take the default matrix
            if (t is Type.TAdt) {
                val heads = matrix.mapNotNull { (it.first() as? SCtor)?.ctor }.toSet()
                if (heads.containsAll(t.info.ctors)) {
                    return t.info.ctors.any { c ->
                        useful(
                            specializeCtor(matrix, c),
                            List(c.fields.size) { SWild } + q.drop(1),
                            instFields(c, t) + types.drop(1),
                        )
                    }
                }
            } else if (t == Type.TBool) {
                val lits = matrix.mapNotNull { (it.first() as? SLit)?.value }.toSet()
                if (true in lits && false in lits) {
                    return listOf(true, false).any { v ->
                        useful(specializeLit(matrix, v), q.drop(1), types.drop(1))
                    }
                }
            }
            // Int/String literals can never be complete
            val defaulted = matrix.filter { it.first() is SWild }.map { it.drop(1) }
            useful(defaulted, q.drop(1), types.drop(1))
        }
    }
}

private fun specializeCtor(matrix: List<List<SPat>>, c: CtorInfo): List<List<SPat>> =
    matrix.mapNotNull { row ->
        when (val h = row.first()) {
            is SWild -> List(c.fields.size) { SWild } + row.drop(1)
            is SCtor -> if (h.ctor == c) h.subs + row.drop(1) else null
            else -> null
        }
    }

private fun specializeLit(matrix: List<List<SPat>>, v: Any): List<List<SPat>> =
    matrix.mapNotNull { row ->
        when (val h = row.first()) {
            is SWild -> row.drop(1)
            is SLit -> if (h.value == v) row.drop(1) else null
            else -> null
        }
    }

private fun specializeTuple(matrix: List<List<SPat>>, n: Int): List<List<SPat>> =
    matrix.mapNotNull { row ->
        when (val h = row.first()) {
            is SWild -> List(n) { SWild } + row.drop(1)
            is STuple -> h.subs + row.drop(1)
            else -> null
        }
    }

/** Specialize a list column to exactly [len] elements (a rest expands to wildcards). */
private fun specializeList(matrix: List<List<SPat>>, len: Int): List<List<SPat>> =
    matrix.mapNotNull { row ->
        when (val h = row.first()) {
            is SWild -> List(len) { SWild } + row.drop(1)
            is SList ->
                if (!h.hasRest) {
                    if (h.pre.size == len) h.pre + row.drop(1) else null
                } else if (h.arity <= len) {
                    h.pre + List(len - h.arity) { SWild } + h.post + row.drop(1)
                } else null
            else -> null
        }
    }

/** One past the longest list pattern in play: lengths beyond behave uniformly. */
private fun listLenBound(matrix: List<List<SPat>>, q: SPat?): Int {
    var m = 0
    for (row in matrix) {
        val h = row.firstOrNull() as? SList ?: continue
        m = maxOf(m, if (h.hasRest) h.arity else h.pre.size)
    }
    (q as? SList)?.let { m = maxOf(m, if (it.hasRest) it.arity else it.pre.size) }
    return m + 1
}

/** Witnesses for a non-exhaustive match over a list: [], [_], [_, _, ..] ... */
internal fun missingListPatterns(rows: List<List<SPat>>, t: Type.TList): List<String> {
    val bound = listLenBound(rows, null)
    val missing = ArrayList<String>()
    for (len in 0..bound) {
        val q = SList(List(len) { SWild }, hasRest = false, post = emptyList())
        if (useful(rows, listOf(q), listOf(t))) {
            val elems = List(len) { "_" } + if (len == bound) listOf("..") else emptyList()
            missing.add("[" + elems.joinToString(", ") + "]")
        }
    }
    return missing
}
