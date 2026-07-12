// Entry: find #dawn-playground, mount the editor + run controls, wire /run.
// Stage 5a scaffolds a bare editor; 5b adds Dawn highlighting + completion and
// 5c the run pipeline and page chrome.
import { EditorView, keymap } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { closeBrackets, completionKeymap } from '@codemirror/autocomplete'
import { bracketMatching, indentOnInput } from '@codemirror/language'
import { dawn } from './dawn-lang'
import './playground.css'

const SAMPLE = `pub fn main() -> Unit !io = {
  let name = "Dawn"
  println("hello from $name")
}
`

function mount(root: HTMLElement) {
  const editorHost = document.createElement('div')
  editorHost.className = 'dp-editor'
  root.appendChild(editorHost)

  new EditorView({
    state: EditorState.create({
      doc: SAMPLE,
      extensions: [
        history(),
        dawn(),
        bracketMatching(),
        closeBrackets(),
        indentOnInput(),
        keymap.of([...completionKeymap, ...defaultKeymap, ...historyKeymap, indentWithTab]),
        EditorView.lineWrapping,
      ],
    }),
    parent: editorHost,
  })
}

const root = document.getElementById('dawn-playground')
if (root) mount(root)
