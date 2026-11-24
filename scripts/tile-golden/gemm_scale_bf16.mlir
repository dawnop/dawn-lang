cuda_tile.module @m {
  entry @gemm_scale_bf16(%arg0: tile<ptr<bf16>>, %arg1: tile<ptr<bf16>>, %arg2: tile<f32>, %arg3: tile<ptr<f32>>) {
    %0 = make_token : token
    %1 = constant <f32: 0.0> : tile<64x64xf32>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 8> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5 = for %6 in (%2 to %3, step %4) : tile<i32> iter_values(%7 = %1) -> (tile<64x64xf32>) {
      %8 = assume div_by<16>, %arg0 : tile<ptr<bf16>>
      %9 = make_tensor_view %8, shape = [256, 256], strides = [256, 1] : tensor_view<256x256xbf16, strides=[256, 1]>
      %10 = make_partition_view %9 : partition_view<tile=(64x32), padding_value = zero, tensor_view<256x256xbf16, strides=[256, 1]>, dim_map=[0, 1]>
      %11, %12, %13 = get_tile_block_id : tile<i32>
      %14, %15 = load_view_tko weak %10[%11, %6] token=%0 : partition_view<tile=(64x32), padding_value = zero, tensor_view<256x256xbf16, strides=[256, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xbf16>, token
      %16 = assume div_by<16>, %arg1 : tile<ptr<bf16>>
      %17 = make_tensor_view %16, shape = [256, 256], strides = [256, 1] : tensor_view<256x256xbf16, strides=[256, 1]>
      %18 = make_partition_view %17 : partition_view<tile=(32x64), padding_value = zero, tensor_view<256x256xbf16, strides=[256, 1]>, dim_map=[0, 1]>
      %19, %20, %21 = get_tile_block_id : tile<i32>
      %22, %23 = load_view_tko weak %18[%6, %20] token=%0 : partition_view<tile=(32x64), padding_value = zero, tensor_view<256x256xbf16, strides=[256, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x64xbf16>, token
      %24 = mmaf %14, %22, %7 : tile<64x32xbf16>, tile<32x64xbf16>, tile<64x64xf32>
      continue %24 : tile<64x64xf32>
    }
    %25 = reshape %arg2 : tile<f32> -> tile<1x1xf32>
    %26 = broadcast %25 : tile<1x1xf32> -> tile<64x64xf32>
    %27 = mulf %5, %26 rounding<nearest_even> : tile<64x64xf32>
    %28 = assume div_by<16>, %arg3 : tile<ptr<f32>>
    %29 = make_tensor_view %28, shape = [256, 256], strides = [256, 1] : tensor_view<256x256xf32, strides=[256, 1]>
    %30 = make_partition_view %29 : partition_view<tile=(64x64), padding_value = zero, tensor_view<256x256xf32, strides=[256, 1]>, dim_map=[0, 1]>
    %31, %32, %33 = get_tile_block_id : tile<i32>
    %34, %35, %36 = get_tile_block_id : tile<i32>
    %37 = store_view_tko weak %27, %30[%31, %35] token=%0 : tile<64x64xf32>, partition_view<tile=(64x64), padding_value = zero, tensor_view<256x256xf32, strides=[256, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
