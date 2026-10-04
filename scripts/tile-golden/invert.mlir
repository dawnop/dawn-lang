cuda_tile.module @m {
  entry @invert(%arg0: tile<ptr<i8>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i8>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xi8, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi8, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi8, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi8>, token
    %9 = exti %7 unsigned : tile<128xi8> -> tile<128xi32>
    %10 = constant <i32: 255> : tile<128xi32>
    %11 = subi %10, %9 : tile<128xi32>
    %12 = trunci %11 : tile<128xi32> -> tile<128xi8>
    %13 = store_view_tko weak %12, %3[%4] token=%8 : tile<128xi8>, partition_view<tile=(128), padding_value = zero, tensor_view<1000xi8, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
