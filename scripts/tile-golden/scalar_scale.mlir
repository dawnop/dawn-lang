cuda_tile.module @m {
  entry @scalar_scale(%arg0: tile<ptr<f64>>, %arg1: tile<f32>, %arg2: tile<ptr<f64>>) {
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
    %15 = ftof %arg1 rounding<nearest_even> : tile<f32> -> tile<f64>
    %16 = reshape %15 : tile<f64> -> tile<1xf64>
    %17 = broadcast %16 : tile<1xf64> -> tile<128xf64>
    %18 = mulf %13, %17 rounding<nearest_even> : tile<128xf64>
    %19 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %20 = broadcast %19 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %21 = offset %20, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %22 = store_ptr_tko weak %21, %18 token=%14 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
