cuda_tile.module @m {
  entry @vadd_f32(%arg0: tile<ptr<f32>>, %arg1: tile<ptr<f32>>, %arg2: tile<ptr<f32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 64> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<64xi32>
    %8 = iota : tile<64xi32>
    %9 = addi %7, %8 : tile<64xi32>
    %10 = reshape %arg0 : tile<ptr<f32>> -> tile<1xptr<f32>>
    %11 = broadcast %10 : tile<1xptr<f32>> -> tile<64xptr<f32>>
    %12 = offset %11, %9 : tile<64xptr<f32>>, tile<64xi32> -> tile<64xptr<f32>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<64xptr<f32>> -> tile<64xf32>, token
    %15 = reshape %arg1 : tile<ptr<f32>> -> tile<1xptr<f32>>
    %16 = broadcast %15 : tile<1xptr<f32>> -> tile<64xptr<f32>>
    %17 = offset %16, %9 : tile<64xptr<f32>>, tile<64xi32> -> tile<64xptr<f32>>
    %18, %19 = load_ptr_tko weak %17 token=%14 : tile<64xptr<f32>> -> tile<64xf32>, token
    %20 = addf %13, %18 rounding<nearest_even> : tile<64xf32>
    %21 = reshape %arg2 : tile<ptr<f32>> -> tile<1xptr<f32>>
    %22 = broadcast %21 : tile<1xptr<f32>> -> tile<64xptr<f32>>
    %23 = offset %22, %9 : tile<64xptr<f32>>, tile<64xi32> -> tile<64xptr<f32>>
    %24 = store_ptr_tko weak %23, %20 token=%19 : tile<64xptr<f32>>, tile<64xf32> -> token
    return
  }
}
