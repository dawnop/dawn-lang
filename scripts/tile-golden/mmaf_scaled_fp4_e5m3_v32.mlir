cuda_tile.module @m {
  entry @mmaf_scaled_fp4_e5m3_v32(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>, %arg4: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(512), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(512), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<512xi32>, token
    %9 = pack %7 : tile<512xi32> -> tile<2048xi8>
    %10 = unpack %9 : tile<2048xi8> -> tile<4096xf4E2M1FN>
    %11 = reshape %10 : tile<4096xf4E2M1FN> -> tile<64x64xf4E2M1FN>
    %12 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %13 = make_tensor_view %12, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %14 = make_partition_view %13 : partition_view<tile=(512), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %15, %16 = load_view_tko weak %14[%4] token=%0 : partition_view<tile=(512), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<512xi32>, token
    %17 = pack %15 : tile<512xi32> -> tile<2048xi8>
    %18 = unpack %17 : tile<2048xi8> -> tile<4096xf4E2M1FN>
    %19 = reshape %18 : tile<4096xf4E2M1FN> -> tile<64x64xf4E2M1FN>
    %20 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %21 = make_tensor_view %20, shape = [64, 2], strides = [2, 1] : tensor_view<64x2xf64, strides=[2, 1]>
    %22 = make_partition_view %21 : partition_view<tile=(64x2), padding_value = zero, tensor_view<64x2xf64, strides=[2, 1]>, dim_map=[0, 1]>
    %23, %24, %25 = get_tile_block_id : tile<i32>
    %26, %27 = load_view_tko weak %22[%4, %24] token=%0 : partition_view<tile=(64x2), padding_value = zero, tensor_view<64x2xf64, strides=[2, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x2xf64>, token
    %28 = ftof %26 rounding<nearest_even> : tile<64x2xf64> -> tile<64x2xf8E5M3FNU>
    %29 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %30 = make_tensor_view %29, shape = [2, 64], strides = [64, 1] : tensor_view<2x64xf64, strides=[64, 1]>
    %31 = make_partition_view %30 : partition_view<tile=(2x64), padding_value = zero, tensor_view<2x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %32, %33 = load_view_tko weak %31[%4, %24] token=%0 : partition_view<tile=(2x64), padding_value = zero, tensor_view<2x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<2x64xf64>, token
    %34 = ftof %32 rounding<nearest_even> : tile<2x64xf64> -> tile<2x64xf8E5M3FNU>
    %35 = constant <f32: 0.0> : tile<64x64xf32>
    %36 = mmaf_scaled %11, %19, %35, %28, %34 : tile<64x64xf4E2M1FN>, tile<64x64xf4E2M1FN>, tile<64x64xf32>, tile<64x2xf8E5M3FNU>, tile<2x64xf8E5M3FNU>
    %37 = ftof %36 rounding<nearest_even> : tile<64x64xf32> -> tile<64x64xf64>
    %38 = assume div_by<16>, %arg4 : tile<ptr<f64>>
    %39 = make_tensor_view %38, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %40 = make_partition_view %39 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %41 = store_view_tko weak %37, %40[%4, %24] token=%0 : tile<64x64xf64>, partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
