cuda_tile.module @m {
  entry @attr_approx(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %14 = ftof %12 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %15 = sqrt %14 rounding<nearest_even> : tile<128xf32>
    %16 = ftof %15 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %17, %18, %19 = get_num_tile_blocks : tile<i32>
    %20 = constant <i32: 256> : tile<i32>
    %21 = muli %17, %20 : tile<i32>
    %22 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %23 = make_tensor_view %22, shape = [%21], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %24 = make_partition_view %23 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %25 = constant <i32: 2> : tile<i32>
    %26 = muli %9, %25 : tile<i32>
    %27 = store_view_tko weak %16, %24[%26] token=%13 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %28 = sqrt %14 rounding<approx> : tile<128xf32>
    %29 = ftof %28 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %30 = constant <i32: 2> : tile<i32>
    %31 = muli %9, %30 : tile<i32>
    %32 = constant <i32: 1> : tile<i32>
    %33 = addi %31, %32 : tile<i32>
    %34 = store_view_tko weak %29, %24[%33] token=%27 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
