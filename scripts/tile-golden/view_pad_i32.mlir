cuda_tile.module @m {
  entry @view_pad_i32(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_tile_block_id : tile<i32>
    %5 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %6 = offset %5, %1 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %7 = make_tensor_view %6, shape = [100], strides = [1] : tensor_view<100xi32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(32), padding_value = zero, tensor_view<100xi32, strides=[1]>, dim_map=[0]>
    %9, %10 = load_view_tko weak %8[%2] token=%0 : partition_view<tile=(32), padding_value = zero, tensor_view<100xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
    %11 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %12 = make_tensor_view %11, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %13 = make_partition_view %12 : partition_view<tile=(32), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %14, %15, %16 = get_tile_block_id : tile<i32>
    %17 = store_view_tko weak %9, %13[%14] token=%0 : tile<32xi32>, partition_view<tile=(32), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
