cuda_tile.module @m {
  entry @scalar_len(%arg0: tile<ptr<f32>>, %arg1: tile<i32>, %arg2: tile<ptr<f32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = reshape %arg1 : tile<i32> -> tile<1xi32>
    %11 = broadcast %10 : tile<1xi32> -> tile<128xi32>
    %12 = cmpi less_than %9, %11, signed : tile<128xi32> -> tile<128xi1>
    %13 = constant <f32: 0.0> : tile<128xf32>
    %14 = reshape %arg0 : tile<ptr<f32>> -> tile<1xptr<f32>>
    %15 = broadcast %14 : tile<1xptr<f32>> -> tile<128xptr<f32>>
    %16 = offset %15, %9 : tile<128xptr<f32>>, tile<128xi32> -> tile<128xptr<f32>>
    %17, %18 = load_ptr_tko weak %16, %12, %13 token=%0 : tile<128xptr<f32>>, tile<128xi1>, tile<128xf32> -> tile<128xf32>, token
    %19 = reshape %arg2 : tile<ptr<f32>> -> tile<1xptr<f32>>
    %20 = broadcast %19 : tile<1xptr<f32>> -> tile<128xptr<f32>>
    %21 = offset %20, %9 : tile<128xptr<f32>>, tile<128xi32> -> tile<128xptr<f32>>
    %22 = store_ptr_tko weak %21, %17, %12 token=%18 : tile<128xptr<f32>>, tile<128xf32>, tile<128xi1> -> token
    return
  }
}
