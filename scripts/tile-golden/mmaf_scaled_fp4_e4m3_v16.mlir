cuda_tile.module @m {
  entry @mmaf_scaled_fp4_e4m3_v16(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<f8E4M3FN>>, %arg3: tile<ptr<f8E4M3FN>>, %arg4: tile<ptr<f64>>) {
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
    %20 = assume div_by<16>, %arg2 : tile<ptr<f8E4M3FN>>
    %21 = make_tensor_view %20, shape = [64, 4], strides = [4, 1] : tensor_view<64x4xf8E4M3FN, strides=[4, 1]>
    %22 = make_partition_view %21 : partition_view<tile=(64x4), padding_value = zero, tensor_view<64x4xf8E4M3FN, strides=[4, 1]>, dim_map=[0, 1]>
    %23, %24, %25 = get_tile_block_id : tile<i32>
    %26, %27 = load_view_tko weak %22[%4, %24] token=%0 : partition_view<tile=(64x4), padding_value = zero, tensor_view<64x4xf8E4M3FN, strides=[4, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x4xf8E4M3FN>, token
    %28 = assume div_by<16>, %arg3 : tile<ptr<f8E4M3FN>>
    %29 = make_tensor_view %28, shape = [4, 64], strides = [64, 1] : tensor_view<4x64xf8E4M3FN, strides=[64, 1]>
    %30 = make_partition_view %29 : partition_view<tile=(4x64), padding_value = zero, tensor_view<4x64xf8E4M3FN, strides=[64, 1]>, dim_map=[0, 1]>
    %31, %32 = load_view_tko weak %30[%4, %24] token=%0 : partition_view<tile=(4x64), padding_value = zero, tensor_view<4x64xf8E4M3FN, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<4x64xf8E4M3FN>, token
    %33 = constant <f32: 0.0> : tile<64x64xf32>
    %34 = mmaf_scaled %11, %19, %33, %26, %31 : tile<64x64xf4E2M1FN>, tile<64x64xf4E2M1FN>, tile<64x64xf32>, tile<64x4xf8E4M3FN>, tile<4x64xf8E4M3FN>
    %35 = ftof %34 rounding<nearest_even> : tile<64x64xf32> -> tile<64x64xf64>
    %36 = assume div_by<16>, %arg4 : tile<ptr<f64>>
    %37 = make_tensor_view %36, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %38 = make_partition_view %37 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %39 = store_view_tko weak %35, %38[%4, %24] token=%0 : tile<64x64xf64>, partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
