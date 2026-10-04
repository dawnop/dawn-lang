cuda_tile.module @m {
  entry @view_gather_pad(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f32>>, %arg2: tile<ptr<f32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = offset %arg1, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %3 = make_tensor_view %2, shape = [16, 6], strides = [6, 1] : tensor_view<16x6xf32, strides=[6, 1]>
    %4 = make_gather_scatter_view %3 : gather_scatter_view<tile=(4x8), padding_value = pos_inf, tensor_view<16x6xf32, strides=[6, 1]>, sparse_dim=0>
    %5 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %6 = make_tensor_view %5, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %7 = make_partition_view %6 : partition_view<tile=(4), padding_value = zero, tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %8, %9, %10 = get_tile_block_id : tile<i32>
    %11, %12 = load_view_tko weak %7[%8] token=%0 : partition_view<tile=(4), padding_value = zero, tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xi32>, token
    %13, %14 = load_view_tko weak %4[%11, %1] token=%12 : gather_scatter_view<tile=(4x8), padding_value = pos_inf, tensor_view<16x6xf32, strides=[6, 1]>, sparse_dim=0>, tile<4xi32>, tile<i32> -> tile<4x8xf32>, token
    %15 = assume div_by<16>, %arg2 : tile<ptr<f32>>
    %16 = make_tensor_view %15, shape = [16, 8], strides = [8, 1] : tensor_view<16x8xf32, strides=[8, 1]>
    %17 = make_partition_view %16 : partition_view<tile=(4x8), padding_value = zero, tensor_view<16x8xf32, strides=[8, 1]>, dim_map=[0, 1]>
    %18, %19, %20 = get_tile_block_id : tile<i32>
    %21 = store_view_tko weak %13, %17[%8, %19] token=%14 : tile<4x8xf32>, partition_view<tile=(4x8), padding_value = zero, tensor_view<16x8xf32, strides=[8, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
