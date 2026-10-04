cuda_tile.module @m {
  entry @assume_same(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %14 = assume same_elements<[4]>, %12 : tile<128xi32>
    %15 = constant <i32: 3> : tile<128xi32>
    %16 = muli %14, %15 : tile<128xi32>
    %17 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %18 = make_tensor_view %17, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %19 = make_partition_view %18 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %20 = store_view_tko weak %16, %19[%9] token=%13 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
