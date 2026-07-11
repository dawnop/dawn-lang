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
        is SWild -> {
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
            is SLit -> null
        }
    }

private fun specializeLit(matrix: List<List<SPat>>, v: Any): List<List<SPat>> =
    matrix.mapNotNull { row ->
        when (val h = row.first()) {
            is SWild -> row.drop(1)
            is SLit -> if (h.value == v) row.drop(1) else null
            is SCtor -> null
        }
    }
