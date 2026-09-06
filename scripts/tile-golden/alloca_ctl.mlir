cuda_tile.module @m {
  entry @alloca_ctl(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
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
    %15 = addf %13, %13 rounding<nearest_even> : tile<128xf64>
    %16 = addf %15, %13 rounding<nearest_even> : tile<128xf64>
    %17 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %18 = broadcast %17 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %19 = offset %18, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %20 = store_ptr_tko weak %19, %16 token=%14 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
