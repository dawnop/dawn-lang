cuda_tile.module @m {
  entry @dtype_e2m1(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [64], strides = [1] : tensor_view<64xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(16), padding_value = zero, tensor_view<64xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(16), padding_value = zero, tensor_view<64xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<16xi32>, token
    %9 = pack %7 : tile<16xi32> -> tile<64xi8>
    %10 = unpack %9 : tile<64xi8> -> tile<128xf4E2M1FN>
    %11 = ftof %10 rounding<nearest_even> : tile<128xf4E2M1FN> -> tile<128xf64>
    %12 = reshape %11 : tile<128xf64> -> tile<1x128xf64>
    %13 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %14 = make_tensor_view %13, shape = [2, 512], strides = [512, 1] : tensor_view<2x512xf64, strides=[512, 1]>
    %15 = make_partition_view %14 : partition_view<tile=(1x128), padding_value = zero, tensor_view<2x512xf64, strides=[512, 1]>, dim_map=[0, 1]>
    %16, %17, %18 = get_tile_block_id : tile<i32>
    %19 = constant <i32: 2> : tile<i32>
    %20 = muli %17, %19 : tile<i32>
    %21 = store_view_tko weak %12, %15[%20, %4] token=%8 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<2x512xf64, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %22 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %23 = make_tensor_view %22, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %24 = make_partition_view %23 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %25, %26 = load_view_tko weak %24[%4] token=%21 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %27 = ftof %25 rounding<nearest_even> : tile<128xf64> -> tile<128xf4E2M1FN>
    %28 = ftof %27 rounding<nearest_even> : tile<128xf4E2M1FN> -> tile<128xf64>
    %29 = reshape %28 : tile<128xf64> -> tile<1x128xf64>
    %30 = constant <i32: 2> : tile<i32>
    %31 = muli %17, %30 : tile<i32>
    %32 = constant <i32: 1> : tile<i32>
    %33 = addi %31, %32 : tile<i32>
    %34 = store_view_tko weak %29, %15[%33, %4] token=%26 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<2x512xf64, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
