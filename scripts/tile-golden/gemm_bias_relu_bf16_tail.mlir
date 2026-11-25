cuda_tile.module @m {
  entry @gemm_bias_relu_bf16_tail(%arg0: tile<ptr<bf16>>, %arg1: tile<ptr<bf16>>, %arg2: tile<ptr<f32>>, %arg3: tile<ptr<bf16>>) {
    %0 = make_token : token
    %1 = constant <f32: 0.0> : tile<64x64xf32>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 10> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5 = for %6 in (%2 to %3, step %4) : tile<i32> iter_values(%7 = %1) -> (tile<64x64xf32>) {
      %8 = assume div_by<16>, %arg0 : tile<ptr<bf16>>
      %9 = make_tensor_view %8, shape = [301, 299], strides = [299, 1] : tensor_view<301x299xbf16, strides=[299, 1]>
      %10 = make_partition_view %9 : partition_view<tile=(64x32), padding_value = zero, tensor_view<301x299xbf16, strides=[299, 1]>, dim_map=[0, 1]>
      %11, %12, %13 = get_tile_block_id : tile<i32>
      %14, %15 = load_view_tko weak %10[%11, %6] token=%0 : partition_view<tile=(64x32), padding_value = zero, tensor_view<301x299xbf16, strides=[299, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xbf16>, token
      %16 = assume div_by<16>, %arg1 : tile<ptr<bf16>>
      %17 = make_tensor_view %16, shape = [299, 203], strides = [203, 1] : tensor_view<299x203xbf16, strides=[203, 1]>
      %18 = make_partition_view %17 : partition_view<tile=(32x64), padding_value = zero, tensor_view<299x203xbf16, strides=[203, 1]>, dim_map=[0, 1]>
      %19, %20, %21 = get_tile_block_id : tile<i32>
      %22, %23 = load_view_tko weak %18[%6, %20] token=%0 : partition_view<tile=(32x64), padding_value = zero, tensor_view<299x203xbf16, strides=[203, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x64xbf16>, token
      %24 = mmaf %14, %22, %7 : tile<64x32xbf16>, tile<32x64xbf16>, tile<64x64xf32>
      continue %24 : tile<64x64xf32>
    }
    %25 = constant <i32: 0> : tile<i32>
    %26 = assume div_by<16>, %arg2 : tile<ptr<f32>>
    %27 = make_tensor_view %26, shape = [1, 203], strides = [203, 1] : tensor_view<1x203xf32, strides=[203, 1]>
    %28 = make_partition_view %27 : partition_view<tile=(1x64), padding_value = zero, tensor_view<1x203xf32, strides=[203, 1]>, dim_map=[0, 1]>
    %29, %30, %31 = get_tile_block_id : tile<i32>
    %32, %33 = load_view_tko weak %28[%25, %30] token=%0 : partition_view<tile=(1x64), padding_value = zero, tensor_view<1x203xf32, strides=[203, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<1x64xf32>, token
    %34 = broadcast %32 : tile<1x64xf32> -> tile<64x64xf32>
    %35 = addf %5, %34 rounding<nearest_even> : tile<64x64xf32>
    %36 = constant <f32: 0.0> : tile<64x64xf32>
    %37 = maxf %35, %36 : tile<64x64xf32>
    %38 = ftof %37 rounding<nearest_even> : tile<64x64xf32> -> tile<64x64xbf16>
    %39 = assume div_by<16>, %arg3 : tile<ptr<bf16>>
    %40 = make_tensor_view %39, shape = [301, 203], strides = [203, 1] : tensor_view<301x203xbf16, strides=[203, 1]>
    %41 = make_partition_view %40 : partition_view<tile=(64x64), padding_value = zero, tensor_view<301x203xbf16, strides=[203, 1]>, dim_map=[0, 1]>
    %42, %43, %44 = get_tile_block_id : tile<i32>
    %45 = store_view_tko weak %38, %41[%42, %30] token=%0 : tile<64x64xbf16>, partition_view<tile=(64x64), padding_value = zero, tensor_view<301x203xbf16, strides=[203, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
