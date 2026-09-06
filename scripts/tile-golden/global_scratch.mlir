cuda_tile.module @m {
  global @scratch <f64: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]> : tile<128xf64>
  entry @global_scratch(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = get_global @scratch : tile<ptr<f64>>
    %7 = reshape %6 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %8 = broadcast %7 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %9 = reshape %5 : tile<i32> -> tile<1xi32>
    %10 = broadcast %9 : tile<1xi32> -> tile<128xi32>
    %11 = iota : tile<128xi32>
    %12 = addi %10, %11 : tile<128xi32>
    %13 = offset %8, %12 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %14, %15 = load_ptr_tko weak %13 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %16 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %17 = broadcast %16 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %18 = offset %17, %12 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %19, %20 = load_ptr_tko weak %18 token=%15 : tile<128xptr<f64>> -> tile<128xf64>, token
    %21 = addf %14, %19 rounding<nearest_even> : tile<128xf64>
    %22 = store_ptr_tko weak %13, %21 token=%20 : tile<128xptr<f64>>, tile<128xf64> -> token
    %23 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %24 = broadcast %23 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %25 = offset %24, %12 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %26 = store_ptr_tko weak %25, %21 token=%22 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
