cuda_tile.module @m {
  entry @layer_norm(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 256> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<256xi32>
    %8 = iota : tile<256xi32>
    %9 = addi %7, %8 : tile<256xi32>
    %10 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %11 = broadcast %10 : tile<1xptr<f64>> -> tile<256xptr<f64>>
    %12 = offset %11, %9 : tile<256xptr<f64>>, tile<256xi32> -> tile<256xptr<f64>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<256xptr<f64>> -> tile<256xf64>, token
    %15 = constant <i32: 0> : tile<i32>
    %16 = reshape %15 : tile<i32> -> tile<1xi32>
    %17 = broadcast %16 : tile<1xi32> -> tile<256xi32>
    %18 = iota : tile<256xi32>
    %19 = addi %17, %18 : tile<256xi32>
    %20 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %21 = broadcast %20 : tile<1xptr<f64>> -> tile<256xptr<f64>>
    %22 = offset %21, %19 : tile<256xptr<f64>>, tile<256xi32> -> tile<256xptr<f64>>
    %23, %24 = load_ptr_tko weak %22 token=%14 : tile<256xptr<f64>> -> tile<256xf64>, token
    %25 = constant <i32: 0> : tile<i32>
    %26 = reshape %25 : tile<i32> -> tile<1xi32>
    %27 = broadcast %26 : tile<1xi32> -> tile<256xi32>
    %28 = iota : tile<256xi32>
    %29 = addi %27, %28 : tile<256xi32>
    %30 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %31 = broadcast %30 : tile<1xptr<f64>> -> tile<256xptr<f64>>
    %32 = offset %31, %29 : tile<256xptr<f64>>, tile<256xi32> -> tile<256xptr<f64>>
    %33, %34 = load_ptr_tko weak %32 token=%24 : tile<256xptr<f64>> -> tile<256xf64>, token
    %35 = constant <f64: 256.0> : tile<256xf64>
    %36 = reduce %13 dim=0 identities=[0.0 : f64] : tile<256xf64> -> tile<f64> (%37: tile<f64>, %38: tile<f64>) {
      %39 = addf %37, %38 rounding<nearest_even> : tile<f64>
      yield %39 : tile<f64>
    }
    %40 = reshape %36 : tile<f64> -> tile<1xf64>
    %41 = broadcast %40 : tile<1xf64> -> tile<256xf64>
    %42 = divf %41, %35 rounding<nearest_even> : tile<256xf64>
    %43 = subf %13, %42 rounding<nearest_even> : tile<256xf64>
    %44 = mulf %43, %43 rounding<nearest_even> : tile<256xf64>
    %45 = reduce %44 dim=0 identities=[0.0 : f64] : tile<256xf64> -> tile<f64> (%46: tile<f64>, %47: tile<f64>) {
      %48 = addf %46, %47 rounding<nearest_even> : tile<f64>
      yield %48 : tile<f64>
    }
    %49 = reshape %45 : tile<f64> -> tile<1xf64>
    %50 = broadcast %49 : tile<1xf64> -> tile<256xf64>
    %51 = divf %50, %35 rounding<nearest_even> : tile<256xf64>
    %52 = constant <f64: 1.0E-5> : tile<256xf64>
    %53 = addf %51, %52 rounding<nearest_even> : tile<256xf64>
    %54 = sqrt %53 rounding<nearest_even> : tile<256xf64>
    %55 = divf %43, %54 rounding<nearest_even> : tile<256xf64>
    %56 = mulf %55, %23 rounding<nearest_even> : tile<256xf64>
    %57 = addf %56, %33 rounding<nearest_even> : tile<256xf64>
    %58 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %59 = broadcast %58 : tile<1xptr<f64>> -> tile<256xptr<f64>>
    %60 = offset %59, %9 : tile<256xptr<f64>>, tile<256xi32> -> tile<256xptr<f64>>
    %61 = store_ptr_tko weak %60, %57 token=%34 : tile<256xptr<f64>>, tile<256xf64> -> token
    return
  }
}
