cuda_tile.module @m {
  entry @fused_rms_norm(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
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
    %15 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %16 = broadcast %15 : tile<1xptr<f64>> -> tile<256xptr<f64>>
    %17 = offset %16, %9 : tile<256xptr<f64>>, tile<256xi32> -> tile<256xptr<f64>>
    %18, %19 = load_ptr_tko weak %17 token=%14 : tile<256xptr<f64>> -> tile<256xf64>, token
    %20 = addf %13, %18 rounding<nearest_even> : tile<256xf64>
    %21 = constant <i32: 0> : tile<i32>
    %22 = reshape %21 : tile<i32> -> tile<1xi32>
    %23 = broadcast %22 : tile<1xi32> -> tile<256xi32>
    %24 = iota : tile<256xi32>
    %25 = addi %23, %24 : tile<256xi32>
    %26 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %27 = broadcast %26 : tile<1xptr<f64>> -> tile<256xptr<f64>>
    %28 = offset %27, %25 : tile<256xptr<f64>>, tile<256xi32> -> tile<256xptr<f64>>
    %29, %30 = load_ptr_tko weak %28 token=%19 : tile<256xptr<f64>> -> tile<256xf64>, token
    %31 = constant <f64: 256.0> : tile<256xf64>
    %32 = mulf %20, %20 rounding<nearest_even> : tile<256xf64>
    %33 = reduce %32 dim=0 identities=[0.0 : f64] : tile<256xf64> -> tile<f64> (%34: tile<f64>, %35: tile<f64>) {
      %36 = addf %34, %35 rounding<nearest_even> : tile<f64>
      yield %36 : tile<f64>
    }
    %37 = reshape %33 : tile<f64> -> tile<1xf64>
    %38 = broadcast %37 : tile<1xf64> -> tile<256xf64>
    %39 = divf %38, %31 rounding<nearest_even> : tile<256xf64>
    %40 = constant <f64: 1.0E-5> : tile<256xf64>
    %41 = addf %39, %40 rounding<nearest_even> : tile<256xf64>
    %42 = sqrt %41 rounding<nearest_even> : tile<256xf64>
    %43 = divf %20, %42 rounding<nearest_even> : tile<256xf64>
    %44 = mulf %43, %29 rounding<nearest_even> : tile<256xf64>
    %45 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %46 = broadcast %45 : tile<1xptr<f64>> -> tile<256xptr<f64>>
    %47 = offset %46, %9 : tile<256xptr<f64>>, tile<256xi32> -> tile<256xptr<f64>>
    %48 = store_ptr_tko weak %47, %44 token=%30 : tile<256xptr<f64>>, tile<256xf64> -> token
    return
  }
}
