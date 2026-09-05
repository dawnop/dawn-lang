cuda_tile.module @m {
  entry @attr_addf(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<i32>
    %7 = reshape %6 : tile<i32> -> tile<1xi32>
    %8 = broadcast %7 : tile<1xi32> -> tile<128xi32>
    %9 = iota : tile<128xi32>
    %10 = addi %8, %9 : tile<128xi32>
    %11 = reshape %5 : tile<i32> -> tile<1xi32>
    %12 = broadcast %11 : tile<1xi32> -> tile<128xi32>
    %13 = iota : tile<128xi32>
    %14 = addi %12, %13 : tile<128xi32>
    %15 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %16 = broadcast %15 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %17 = offset %16, %14 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %18, %19 = load_ptr_tko weak %17 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %20 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %21 = broadcast %20 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %22 = offset %21, %10 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %23, %24 = atomic_rmw_tko relaxed device %22, addf, %18 token=%19 : tile<128xptr<f64>>, tile<128xf64> -> tile<128xf64>, token
    return
  }
}
