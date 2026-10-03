cuda_tile.module @m {
  entry @flash_attn(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 1024> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1x1xi32>
    %7 = broadcast %6 : tile<1x1xi32> -> tile<32x32xi32>
    %8 = iota : tile<32xi32>
    %9 = reshape %8 : tile<32xi32> -> tile<32x1xi32>
    %10 = broadcast %9 : tile<32x1xi32> -> tile<32x32xi32>
    %11 = constant <i32: 32> : tile<32x32xi32>
    %12 = muli %10, %11 : tile<32x32xi32>
    %13 = addi %7, %12 : tile<32x32xi32>
    %14 = iota : tile<32xi32>
    %15 = reshape %14 : tile<32xi32> -> tile<1x32xi32>
    %16 = broadcast %15 : tile<1x32xi32> -> tile<32x32xi32>
    %17 = addi %13, %16 : tile<32x32xi32>
    %18 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %19 = broadcast %18 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %20 = offset %19, %17 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %21, %22 = load_ptr_tko weak %20 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %23 = constant <f64: 0.0> : tile<32x32xf64>
    %24 = constant <f64: 1.0> : tile<32x32xf64>
    %25 = constant <f64: 0.17677669529663687> : tile<32x32xf64>
    %26 = constant <f64: -Infinity> : tile<32x32xf64>
    %27 = constant <i32: 0> : tile<i32>
    %28 = constant <i32: 2> : tile<i32>
    %29 = constant <i32: 1> : tile<i32>
    %30, %31, %32, %33 = for %34 in (%27 to %28, step %29) : tile<i32> iter_values(%35 = %26, %36 = %23, %37 = %23, %38 = %22) -> (tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>, token) {
      %39 = constant <i32: 1024> : tile<i32>
      %40 = muli %34, %39 : tile<i32>
      %41 = reshape %40 : tile<i32> -> tile<1x1xi32>
      %42 = broadcast %41 : tile<1x1xi32> -> tile<32x32xi32>
      %43 = iota : tile<32xi32>
      %44 = reshape %43 : tile<32xi32> -> tile<32x1xi32>
      %45 = broadcast %44 : tile<32x1xi32> -> tile<32x32xi32>
      %46 = addi %42, %45 : tile<32x32xi32>
      %47 = iota : tile<32xi32>
      %48 = reshape %47 : tile<32xi32> -> tile<1x32xi32>
      %49 = broadcast %48 : tile<1x32xi32> -> tile<32x32xi32>
      %50 = constant <i32: 32> : tile<32x32xi32>
      %51 = muli %49, %50 : tile<32x32xi32>
      %52 = addi %46, %51 : tile<32x32xi32>
      %53 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %54 = broadcast %53 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %55 = offset %54, %52 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %56, %57 = load_ptr_tko weak %55 token=%38 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %58 = reshape %40 : tile<i32> -> tile<1x1xi32>
      %59 = broadcast %58 : tile<1x1xi32> -> tile<32x32xi32>
      %60 = iota : tile<32xi32>
      %61 = reshape %60 : tile<32xi32> -> tile<32x1xi32>
      %62 = broadcast %61 : tile<32x1xi32> -> tile<32x32xi32>
      %63 = constant <i32: 32> : tile<32x32xi32>
      %64 = muli %62, %63 : tile<32x32xi32>
      %65 = addi %59, %64 : tile<32x32xi32>
      %66 = iota : tile<32xi32>
      %67 = reshape %66 : tile<32xi32> -> tile<1x32xi32>
      %68 = broadcast %67 : tile<1x32xi32> -> tile<32x32xi32>
      %69 = addi %65, %68 : tile<32x32xi32>
      %70 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %71 = broadcast %70 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %72 = offset %71, %69 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %73, %74 = load_ptr_tko weak %72 token=%57 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %75 = mmaf %21, %56, %23 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      %76 = mulf %75, %25 rounding<nearest_even> : tile<32x32xf64>
      %77 = scan %76 dim=1 reverse=false identities=[-Infinity : f64] : tile<32x32xf64> -> tile<32x32xf64> (%78: tile<f64>, %79: tile<f64>) {
        %80 = maxf %78, %79 : tile<f64>
        yield %80 : tile<f64>
      }
      %81 = scan %76 dim=1 reverse=true identities=[-Infinity : f64] : tile<32x32xf64> -> tile<32x32xf64> (%82: tile<f64>, %83: tile<f64>) {
        %84 = maxf %82, %83 : tile<f64>
        yield %84 : tile<f64>
      }
      %85 = maxf %77, %81 : tile<32x32xf64>
      %86 = maxf %35, %85 : tile<32x32xf64>
      %87 = subf %76, %86 rounding<nearest_even> : tile<32x32xf64>
      %88 = exp %87 : tile<32x32xf64>
      %89 = subf %35, %86 rounding<nearest_even> : tile<32x32xf64>
      %90 = exp %89 : tile<32x32xf64>
      %91 = mulf %36, %90 rounding<nearest_even> : tile<32x32xf64>
      %92 = mmaf %88, %24, %91 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      %93 = mulf %37, %90 rounding<nearest_even> : tile<32x32xf64>
      %94 = mmaf %88, %73, %93 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %86, %92, %94, %74 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>, token
    }
    %95 = divf %32, %31 rounding<nearest_even> : tile<32x32xf64>
    %96 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %97 = broadcast %96 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %98 = offset %97, %17 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %99 = store_ptr_tko weak %98, %95 token=%33 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
