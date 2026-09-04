cuda_tile.module @m {
  entry @llama_rms(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %11 = broadcast %10 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %12 = offset %11, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %15 = constant <i32: 0> : tile<i32>
    %16 = reshape %15 : tile<i32> -> tile<1xi32>
    %17 = broadcast %16 : tile<1xi32> -> tile<128xi32>
    %18 = iota : tile<128xi32>
    %19 = addi %17, %18 : tile<128xi32>
    %20 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %21 = broadcast %20 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %22 = offset %21, %19 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %23, %24 = load_ptr_tko weak %22 token=%14 : tile<128xptr<f64>> -> tile<128xf64>, token
    %25 = mulf %13, %13 rounding<nearest_even> : tile<128xf64>
    %26 = reduce %25 dim=0 identities=[0.0 : f64] : tile<128xf64> -> tile<f64> (%27: tile<f64>, %28: tile<f64>) {
      %29 = addf %27, %28 rounding<nearest_even> : tile<f64>
      yield %29 : tile<f64>
    }
    %30 = reshape %26 : tile<f64> -> tile<1xf64>
    %31 = broadcast %30 : tile<1xf64> -> tile<128xf64>
    %32 = constant <f64: 128.0> : tile<128xf64>
    %33 = divf %31, %32 rounding<nearest_even> : tile<128xf64>
    %34 = constant <f64: 1.0E-5> : tile<128xf64>
    %35 = addf %33, %34 rounding<nearest_even> : tile<128xf64>
    %36 = rsqrt %35 : tile<128xf64>
    %37 = mulf %13, %36 rounding<nearest_even> : tile<128xf64>
    %38 = mulf %37, %23 rounding<nearest_even> : tile<128xf64>
    %39 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %40 = broadcast %39 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %41 = offset %40, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %42 = store_ptr_tko weak %41, %38 token=%24 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
