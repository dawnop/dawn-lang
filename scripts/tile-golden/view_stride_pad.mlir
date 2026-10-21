cuda_tile.module @m {
  entry @view_stride_pad(%arg0: tile<ptr<f32>>, %arg1: tile<ptr<f32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = assume div_by<16>, %arg0 : tile<ptr<f32>>
    %3 = offset %2, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %4 = make_tensor_view %3, shape = [90], strides = [1] : tensor_view<90xf32, strides=[1]>
    %5 = make_strided_view %4 : strided_view<tile=(4), traversal_strides=[8], padding_value = nan, tensor_view<90xf32, strides=[1]>, dim_map=[0]>
    %6, %7, %8 = get_tile_block_id : tile<i32>
    %9, %10 = load_view_tko weak %5[%6] token=%0 : strided_view<tile=(4), traversal_strides=[8], padding_value = nan, tensor_view<90xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xf32>, token
    %11 = assume div_by<16>, %arg1 : tile<ptr<f32>>
    %12 = make_tensor_view %11, shape = [48], strides = [1] : tensor_view<48xf32, strides=[1]>
    %13 = make_partition_view %12 : partition_view<tile=(4), padding_value = zero, tensor_view<48xf32, strides=[1]>, dim_map=[0]>
    %14, %15, %16 = get_tile_block_id : tile<i32>
    %17 = store_view_tko weak %9, %13[%14] token=%0 : tile<4xf32>, partition_view<tile=(4), padding_value = zero, tensor_view<48xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
