// Curated starter programs, shown as "files" in the explorer sidebar. Each
// must compile and run as-is under `dawn run`.
export interface Sample {
  label: string
  file: string
  code: string
}

export const SAMPLES: Sample[] = [
  {
    label: 'Hello',
    file: 'hello.dawn',
    code: `pub fn main() -> Unit !io = {
  let name = "Dawn"
  println("hello from $name")
}
`,
  },
  {
    label: 'ADT + match',
    file: 'shapes.dawn',
    code: `type Shape =
  | Circle(r: Float)
  | Rect(w: Float, h: Float)

fn area(s: Shape) -> Float =
  match s {
    Circle(r) -> 3.14159 * r * r
    Rect(w, h) -> w * h
  }

pub fn main() -> Unit !io = {
  println(to_string(area(Circle(2.0))))
  println(to_string(area(Rect(3.0, 4.0))))
}
`,
  },
  {
    label: 'comptime',
    file: 'comptime.dawn',
    code: `fn fib(n: Int) -> Int =
  if n < 2 { n } else { fib(n - 1) + fib(n - 2) }

# evaluated at compile time, baked into the constant pool
const FIB10: Int = comptime { fib(10) }

pub fn main() -> Unit !io = println(to_string(FIB10))
`,
  },
  {
    label: 'effects',
    file: 'effects.dawn',
    code: `# pure: no !io in the signature
fn double(n: Int) -> Int = n * 2

# touches IO, so the signature must say !io
fn shout(s: String) -> Unit !io = println("$s!")

pub fn main() -> Unit !io = {
  shout(to_string(double(21)))
}
`,
  },
]
