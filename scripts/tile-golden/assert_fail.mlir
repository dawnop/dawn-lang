cuda_tile.module @m {
  entry @assert_fail(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %14 = constant <i32: 0> : tile<128xi32>
    %15 = cmpi less_than %12, %14, signed : tile<128xi32> -> tile<128xi1>
    assert %15, "tile-golden: a lane reached the limit" : tile<128xi1>
    %16 = constant <i32: 1> : tile<128xi32>
    %17 = addi %12, %16 : tile<128xi32>
    %18 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %19 = make_tensor_view %18, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %20 = make_partition_view %19 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %21 = store_view_tko weak %17, %20[%9] token=%13 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
