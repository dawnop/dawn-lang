cuda_tile.module @m {
  entry @view_stride_pad(%arg0: tile<ptr<f32>>, %arg1: tile<ptr<f32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = offset %arg0, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %3 = make_tensor_view %2, shape = [90], strides = [1] : tensor_view<90xf32, strides=[1]>
    %4 = make_strided_view %3 : strided_view<tile=(4), traversal_strides=[8], padding_value = nan, tensor_view<90xf32, strides=[1]>, dim_map=[0]>
    %5, %6, %7 = get_tile_block_id : tile<i32>
    %8, %9 = load_view_tko weak %4[%5] token=%0 : strided_view<tile=(4), traversal_strides=[8], padding_value = nan, tensor_view<90xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xf32>, token
    %10 = assume div_by<16>, %arg1 : tile<ptr<f32>>
    %11 = make_tensor_view %10, shape = [48], strides = [1] : tensor_view<48xf32, strides=[1]>
    %12 = make_partition_view %11 : partition_view<tile=(4), padding_value = zero, tensor_view<48xf32, strides=[1]>, dim_map=[0]>
    %13, %14, %15 = get_tile_block_id : tile<i32>
    %16 = store_view_tko weak %8, %12[%13] token=%9 : tile<4xf32>, partition_view<tile=(4), padding_value = zero, tensor_view<48xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
