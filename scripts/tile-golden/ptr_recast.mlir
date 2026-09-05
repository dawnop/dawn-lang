cuda_tile.module @m {
  entry @ptr_recast(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %7 = broadcast %6 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = offset %7, %11 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %13 = ptr_to_ptr %12 : tile<128xptr<i32>> -> tile<128xptr<f32>>
    %14, %15 = load_ptr_tko weak %13 token=%0 : tile<128xptr<f32>> -> tile<128xf32>, token
    %16 = ftof %14 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %17 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %18 = broadcast %17 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %19 = offset %18, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %20 = store_ptr_tko weak %19, %16 token=%15 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
