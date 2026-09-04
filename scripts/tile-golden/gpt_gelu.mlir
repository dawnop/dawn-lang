cuda_tile.module @m {
  entry @gpt_gelu(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
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
    %15 = mulf %13, %13 rounding<nearest_even> : tile<128xf64>
    %16 = mulf %13, %15 rounding<nearest_even> : tile<128xf64>
    %17 = constant <f64: 0.7978845608028654> : tile<128xf64>
    %18 = constant <f64: 0.044715> : tile<128xf64>
    %19 = mulf %18, %16 rounding<nearest_even> : tile<128xf64>
    %20 = addf %13, %19 rounding<nearest_even> : tile<128xf64>
    %21 = mulf %17, %20 rounding<nearest_even> : tile<128xf64>
    %22 = constant <f64: 1.0> : tile<128xf64>
    %23 = tanh %21 : tile<128xf64>
    %24 = addf %22, %23 rounding<nearest_even> : tile<128xf64>
    %25 = constant <f64: 0.5> : tile<128xf64>
    %26 = mulf %25, %13 rounding<nearest_even> : tile<128xf64>
    %27 = mulf %26, %24 rounding<nearest_even> : tile<128xf64>
    %28 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %29 = broadcast %28 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %30 = offset %29, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %31 = store_ptr_tko weak %30, %27 token=%14 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
