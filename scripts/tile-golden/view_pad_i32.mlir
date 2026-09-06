cuda_tile.module @m {
  entry @view_pad_i32(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_tile_block_id : tile<i32>
    %5 = offset %arg0, %1 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %6 = make_tensor_view %5, shape = [100], strides = [1] : tensor_view<100xi32, strides=[1]>
    %7 = make_partition_view %6 : partition_view<tile=(32), padding_value = zero, tensor_view<100xi32, strides=[1]>, dim_map=[0]>
    %8 = offset %arg1, %1 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %9 = make_tensor_view %8, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %10 = make_partition_view %9 : partition_view<tile=(32), tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %11, %12 = load_view_tko weak %7[%2] token=%0 : partition_view<tile=(32), padding_value = zero, tensor_view<100xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
    %13 = store_view_tko weak %11, %10[%2] token=%12 : tile<32xi32>, partition_view<tile=(32), tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
