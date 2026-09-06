cuda_tile.module @m {
  entry @view_gather_pad(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f32>>, %arg2: tile<ptr<f32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_tile_block_id : tile<i32>
    %5 = constant <i32: 4> : tile<i32>
    %6 = muli %2, %5 : tile<i32>
    %7 = reshape %6 : tile<i32> -> tile<1xi32>
    %8 = broadcast %7 : tile<1xi32> -> tile<4xi32>
    %9 = iota : tile<4xi32>
    %10 = addi %8, %9 : tile<4xi32>
    %11 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %12 = broadcast %11 : tile<1xptr<i32>> -> tile<4xptr<i32>>
    %13 = offset %12, %10 : tile<4xptr<i32>>, tile<4xi32> -> tile<4xptr<i32>>
    %14, %15 = load_ptr_tko weak %13 token=%0 : tile<4xptr<i32>> -> tile<4xi32>, token
    %16 = offset %arg1, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %17 = make_tensor_view %16, shape = [16, 6], strides = [6, 1] : tensor_view<16x6xf32, strides=[6, 1]>
    %18 = make_gather_scatter_view %17 : gather_scatter_view<tile=(4x8), padding_value = pos_inf, tensor_view<16x6xf32, strides=[6, 1]>, sparse_dim=0>
    %19 = offset %arg2, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %20 = make_tensor_view %19, shape = [16, 8], strides = [8, 1] : tensor_view<16x8xf32, strides=[8, 1]>
    %21 = make_partition_view %20 : partition_view<tile=(4x8), tensor_view<16x8xf32, strides=[8, 1]>, dim_map=[0, 1]>
    %22, %23 = load_view_tko weak %18[%14, %1] token=%15 : gather_scatter_view<tile=(4x8), padding_value = pos_inf, tensor_view<16x6xf32, strides=[6, 1]>, sparse_dim=0>, tile<4xi32>, tile<i32> -> tile<4x8xf32>, token
    %24 = store_view_tko weak %22, %21[%2, %1] token=%23 : tile<4x8xf32>, partition_view<tile=(4x8), tensor_view<16x8xf32, strides=[8, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
