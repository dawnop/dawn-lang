cuda_tile.module @m {
  entry @swiglu_act(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
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
    %15 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %16 = broadcast %15 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %17 = offset %16, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %18, %19 = load_ptr_tko weak %17 token=%14 : tile<128xptr<f64>> -> tile<128xf64>, token
    %20 = constant <f64: 1.0> : tile<128xf64>
    %21 = negf %13 : tile<128xf64>
    %22 = exp %21 : tile<128xf64>
    %23 = addf %20, %22 rounding<nearest_even> : tile<128xf64>
    %24 = divf %13, %23 rounding<nearest_even> : tile<128xf64>
    %25 = mulf %24, %18 rounding<nearest_even> : tile<128xf64>
    %26 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %27 = broadcast %26 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %28 = offset %27, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %29 = store_ptr_tko weak %28, %25 token=%19 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
