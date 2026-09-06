cuda_tile.module @m {
  entry @view_stride_pad(%arg0: tile<ptr<f32>>, %arg1: tile<ptr<f32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_tile_block_id : tile<i32>
    %5 = offset %arg0, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %6 = make_tensor_view %5, shape = [90], strides = [1] : tensor_view<90xf32, strides=[1]>
    %7 = make_strided_view %6 : strided_view<tile=(4), traversal_strides=[8], padding_value = nan, tensor_view<90xf32, strides=[1]>, dim_map=[0]>
    %8 = offset %arg1, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %9 = make_tensor_view %8, shape = [48], strides = [1] : tensor_view<48xf32, strides=[1]>
    %10 = make_partition_view %9 : partition_view<tile=(4), tensor_view<48xf32, strides=[1]>, dim_map=[0]>
    %11, %12 = load_view_tko weak %7[%2] token=%0 : strided_view<tile=(4), traversal_strides=[8], padding_value = nan, tensor_view<90xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xf32>, token
    %13 = store_view_tko weak %11, %10[%2] token=%12 : tile<4xf32>, partition_view<tile=(4), tensor_view<48xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
