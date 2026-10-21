cuda_tile.module @m {
  entry @token_fences(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = gdc_wait_tko token = %0 -> token
    %7 = reshape %5 : tile<i32> -> tile<1xi32>
    %8 = broadcast %7 : tile<1xi32> -> tile<128xi32>
    %9 = iota : tile<128xi32>
    %10 = addi %8, %9 : tile<128xi32>
    %11 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %12 = broadcast %11 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %13 = offset %12, %10 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %14, %15 = load_ptr_tko weak %13 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %16 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %17 = broadcast %16 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %18 = offset %17, %10 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %19 = store_ptr_tko weak %18, %14 token=%6 : tile<128xptr<f64>>, tile<128xf64> -> token
    %20 = memory_fence_alias_tko %19
    %21, %22 = load_ptr_tko weak %18 token=%20 : tile<128xptr<f64>> -> tile<128xf64>, token
    %23 = addf %21, %14 rounding<nearest_even> : tile<128xf64>
    %24 = store_ptr_tko weak %18, %23 token=%22 : tile<128xptr<f64>>, tile<128xf64> -> token
    %25 = gdc_launch_dependents_tko token = %24 -> token
    return
  }
}
