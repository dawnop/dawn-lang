cuda_tile.module @m {
  entry @vadd_f32(%arg0: tile<ptr<f32>>, %arg1: tile<ptr<f32>>, %arg2: tile<ptr<f32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 64> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<f32>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf32, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf32>, token
    %14 = assume div_by<16>, %arg1 : tile<ptr<f32>>
    %15 = make_tensor_view %14, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf32, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf32, strides=[1]>, dim_map=[0]>
    %17, %18 = load_view_tko weak %16[%9] token=%13 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf32>, token
    %19 = addf %12, %17 rounding<nearest_even> : tile<64xf32>
    %20 = assume div_by<16>, %arg2 : tile<ptr<f32>>
    %21 = make_tensor_view %20, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf32, strides=[1]>
    %22 = make_partition_view %21 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf32, strides=[1]>, dim_map=[0]>
    %23 = store_view_tko weak %19, %22[%9] token=%18 : tile<64xf32>, partition_view<tile=(64), padding_value = zero, tensor_view<?xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
