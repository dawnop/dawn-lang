#!/usr/bin/env python3
"""Instrument a private selfhost copy and apply one compiling LSP mutant."""

from pathlib import Path
import sys


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label} mutation anchor occurs {count} times")
    return text.replace(old, new)


def replace_section(text, start, end, new, label):
    starts = text.count(start)
    ends = text.count(end)
    if starts != 1 or ends != 1:
        raise SystemExit(f"{label} section anchors occur {starts}/{ends} times")
    begin = text.index(start)
    finish = text.index(end, begin)
    return text[:begin] + new + "\n\n" + text[finish:]


def instrument(jreflect):
    text = jreflect.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "use std/set\n",
        "use std/set\nuse std/io\n",
        "lease instrumentation import",
    )
    text = replace_once(
        text,
        """pub fn jsig_for(jars: List[String]) -> JsigLease !io = {
  let loader = loader_for(jars)
  lease_with(loader, target_has_asm(loader.base))
}""",
        """pub fn jsig_for(jars: List[String]) -> JsigLease !io = {
  let loader = loader_for(jars)
  let lease = lease_with(loader, target_has_asm(loader.base))
  let count = len(jars)
  io.eprintln("LSP_WORKSPACE_LEASE create " ++ to_string(count))
  JsigLease {
    jsig: lease.jsig,
    close: () => {
      lease.close()
      io.eprintln("LSP_WORKSPACE_LEASE close " ++ to_string(count))
      match io.getenv("DAWN_LSP_TEST_CLOSE_PANIC") {
        Some(mode) ->
          if mode == "project" && count > 0 {
            panic("injected project lease close failure")
          }
        None -> ()
      }
    }
  }
}""",
        "lease instrumentation",
    )
    jreflect.write_text(text, encoding="utf-8")


def mutate(name, server, main, analyze):
    server_text = server.read_text(encoding="utf-8")
    main_text = main.read_text(encoding="utf-8")

    if name == "observe":
        pass
    elif name == "single-overlay":
        server_text = replace_once(
            server_text,
            "      let loaded = load_entries_over(ws0.plan, entries, overlay)",
            """      let last = entries[len(entries) - 1]
      let single: Map[String, String] = map.insert(
        map.empty(), last, map.get(overlay, last).expect("single overlay"))
      let loaded = load_entries_over(ws0.plan, entries, single)""",
            name,
        )
    elif name == "didclose-no-rebuild":
        server_text = replace_once(
            server_text,
            "              Ready(ws) -> Ready(rebuild_workspace(st, Workspace { ..ws, path_by_uri: paths }))",
            "              Ready(ws) -> Ready(Workspace { ..ws, path_by_uri: paths })",
            name,
        )
    elif name == "only-current-diagnostics":
        old = """      let affected = slot_uris(before)
      let slot = match before {
        Ready(ws) -> Ready(rebuild_workspace(st, ws))
        Unavailable(ws) -> Unavailable(unavailable_workspace(
          st, ws.plan, ws.path_by_uri, ws.problem))
      }
      install_workspace(st, identity, slot, affected)"""
        new = """      let slot = match before {
        Ready(ws) -> Ready(rebuild_workspace(st, ws))
        Unavailable(ws) -> Unavailable(unavailable_workspace(
          st, ws.plan, ws.path_by_uri, ws.problem))
      }
      let next = LspState {
        ..st,
        workspaces: map.insert(st.workspaces, identity.lookup_key, slot)
      }
      publish_uris(next, set.from([old.uri]))
      next"""
        server_text = replace_once(server_text, old, new, name)
    elif name == "skip-empty-diagnostics":
        old = """  for uri in sort(set.to_list(uris)) {
    var fields: List[(String, Json)] = [
      ("uri", JStr(uri)),
      ("diagnostics", JArr(diagnostics_for_uri(st, uri)))
    ]
    match map.get(st.docs, uri) {
      Some(d) -> { fields = fields ++ [("version", JInt(d.version))] }
      None -> ()
    }
    notify("textDocument/publishDiagnostics", jobj(fields))
  }"""
        new = """  for uri in sort(set.to_list(uris)) {
    let values = diagnostics_for_uri(st, uri)
    if len(values) > 0 {
      var fields: List[(String, Json)] = [
        ("uri", JStr(uri)),
        ("diagnostics", JArr(values))
      ]
      match map.get(st.docs, uri) {
        Some(d) -> { fields = fields ++ [("version", JInt(d.version))] }
        None -> ()
      }
      notify("textDocument/publishDiagnostics", jobj(fields))
    }
  }"""
        server_text = replace_once(server_text, old, new, name)
    elif name == "drop-diagnostics-version":
        old = """    var fields: List[(String, Json)] = [
      ("uri", JStr(uri)),
      ("diagnostics", JArr(diagnostics_for_uri(st, uri)))
    ]
    match map.get(st.docs, uri) {
      Some(d) -> { fields = fields ++ [("version", JInt(d.version))] }
      None -> ()
    }
    notify("textDocument/publishDiagnostics", jobj(fields))"""
        new = """    notify("textDocument/publishDiagnostics", jobj([
      ("uri", JStr(uri)),
      ("diagnostics", JArr(diagnostics_for_uri(st, uri)))
    ]))"""
        server_text = replace_once(server_text, old, new, name)
    elif name == "wrong-source-view":
        old = """        Some(d) -> {
          out = append_diagnostic(out, uri, diagnostic_json(d.view, d.ls, ld.d))
          matched = true
        }"""
        new = """        Some(_) -> {
          let wrong_uri = sort(map.keys(st.docs))[0]
          let wrong = map.get(st.docs, wrong_uri).expect("wrong diagnostic document")
          out = append_diagnostic(out, uri, diagnostic_json(wrong.view, wrong.ls, ld.d))
          matched = true
        }"""
        server_text = replace_once(server_text, old, new, name)
    elif name == "duplicate-last-wins":
        old = """      Some(before) -> {
        if before != d.text { conflicts = set.insert(conflicts, path) }
      }"""
        new = """      Some(_) -> {
        texts = map.insert(texts, path, d.text)
        overlay = map.insert(overlay, path, d.text)
      }"""
        server_text = replace_once(server_text, old, new, name)
    elif name == "ignore-unsaved-module":
        new = """fn workspace_modules(ws: Workspace, current_uri: String) -> Map[String, String] = {
  let current_entry = map.get(ws.entry_by_uri, current_uri).expect("current workspace entry")
  map.remove(ws.plan.modules.by_use, current_entry)
}"""
        server_text = replace_section(
            server_text,
            "fn workspace_modules(",
            "## The only semantic ownership seam.",
            new,
            name,
        )
    elif name == "current-module-self":
        new = """fn workspace_modules(ws: Workspace, _current_uri: String) -> Map[String, String] = {
  var out = ws.plan.modules.by_use
  for uri in sort(map.keys(ws.entry_by_uri)) {
    let entry = map.get(ws.entry_by_uri, uri).expect("workspace entry")
    let path = map.get(ws.path_by_uri, uri).expect("workspace path")
    out = map.insert(out, entry, path)
  }
  out
}"""
        server_text = replace_section(
            server_text,
            "fn workspace_modules(",
            "## The only semantic ownership seam.",
            new,
            name,
        )
    elif name == "extensionless-project-member":
        analyze_text = analyze.read_text(encoding="utf-8")
        new = """pub fn project_module_path(plan: ProjectPlan, file: String) -> Option[String] !io = {
  let mod_path = module_path_of(canon(plan.source.source_root), canon(file))
  if len(bad_segments(mod_path)) == 0 { Some(mod_path) } else { None }
}"""
        analyze_text = replace_section(
            analyze_text,
            "pub fn project_module_path(",
            "## Everything .dawn under `dir`, recursively, full display paths.",
            new,
            name,
        )
        analyze.write_text(analyze_text, encoding="utf-8")
    elif name == "project-only-identity":
        server_text = replace_once(
            server_text,
            "lookup_key: workspace_key_part(project) ++ workspace_key_part(source_root)",
            "lookup_key: workspace_key_part(project)",
            name,
        )
    elif name == "global-definition":
        new = """  let _ = workspace_key
  let _ = definition_root
  for uri in sort(map.keys(st.docs)) {
    let d2 = map.get(st.docs, uri).expect("open document")
    match d2.canonical_path {
      Some(path) ->
        if path == dc {
          return Some(jobj([
            ("uri", JStr(uri)),
            ("range", jrange(d2.view, d2.ls, lo, hi))
          ]))
        }
      None -> ()
    }
  }"""
        server_text = replace_section(
            server_text,
            "  let slot = match workspace_key {",
            "  match io.read_file(dc) {",
            new,
            name,
        )
    elif name == "merged-java-lease":
        old = "  match catch_fault(() => jsig_for(jars)) {"
        new = """  let selected = match io.getenv("DAWN_LSP_MUTANT_MERGED_CP") {
    Some(value) -> str.split(value, path_sep())
    None -> jars
  }
  match catch_fault(() => jsig_for(selected)) {"""
        main_text = replace_once(main_text, old, new, name)
    elif name == "last-close-retains-lease":
        server_text = replace_once(
            server_text,
            "              Ready(ws) -> close_lease(ws.lease)",
            "              Ready(_) -> ()",
            name,
        )
    elif name == "close-uncaught":
        old = """fn close_lease(lease: JsigLease) -> Unit !io =
  match catch_panic(() => lease.close()) {
    Ok(_) -> ()
    Err(e) -> io.eprintln("lsp: failed to close a Java signature lease: " ++ e.message)
  }"""
        new = """fn close_lease(lease: JsigLease) -> Unit !io = lease.close()"""
        server_text = replace_once(server_text, old, new, name)
    elif name == "retry-unavailable-on-change":
        old = """      let slot = match before {
        Ready(ws) -> Ready(rebuild_workspace(st, ws))
        Unavailable(ws) -> Unavailable(unavailable_workspace(
          st, ws.plan, ws.path_by_uri, ws.problem))
      }"""
        new = """      let slot = match before {
        Ready(ws) -> Ready(rebuild_workspace(st, ws))
        Unavailable(ws) -> activate_workspace(st, ws.plan, ws.path_by_uri)
      }"""
        server_text = replace_once(server_text, old, new, name)
    elif name == "exit-bypasses-cleanup":
        old = """            LgExit(code) -> {
              pending = None
              exit_status = Some(code)
              serving = false
            }"""
        new = """            LgExit(code) -> {
              pending = None
              let _ = io.exit(code)
              serving = false
            }"""
        server_text = replace_once(server_text, old, new, name)
    elif name == "external-owner-clears":
        old = """            st = LspState {
              ..st,
              workspaces: map.remove(st.workspaces, identity.lookup_key)
            }
            publish_uris(st, affected)
            match before {"""
        new = """            st = LspState {
              ..st,
              workspaces: map.remove(st.workspaces, identity.lookup_key)
            }
            for affected_uri in sort(set.to_list(affected)) {
              notify("textDocument/publishDiagnostics", jobj([
                ("uri", JStr(affected_uri)),
                ("diagnostics", JArr([]))
              ]))
            }
            match before {"""
        server_text = replace_once(server_text, old, new, name)
    elif name == "standalone-system-loader":
        main_text = replace_once(
            main_text,
            "fn lsp_standalone_lease() -> JsigLease !io = jsig_for([])",
            """fn lsp_standalone_lease() -> JsigLease !io =
  JsigLease { jsig: jsig_real(), close: () => () }""",
            name,
        )
    else:
        raise SystemExit(f"unknown mutation: {name}")

    server.write_text(server_text, encoding="utf-8")
    main.write_text(main_text, encoding="utf-8")


def main_entry():
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py MODE PRIVATE-SELFHOST")
    name = sys.argv[1]
    root = Path(sys.argv[2])
    server = root / "src/lsp/server.dawn"
    main = root / "src/main.dawn"
    jreflect = root / "src/jvm/jreflect.dawn"
    analyze = root / "src/driver/analyze.dawn"
    instrument(jreflect)
    mutate(name, server, main, analyze)


if __name__ == "__main__":
    main_entry()
