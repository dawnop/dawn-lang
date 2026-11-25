cuda_tile.module @m {
  entry @gemm_bf16_tail_sm90(%arg0: tile<ptr<bf16>>, %arg1: tile<ptr<bf16>>, %arg2: tile<ptr<f32>>) {
    %0 = make_token : token
    %1 = constant <f32: 0.0> : tile<128x128xf32>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 5> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5 = for %6 in (%2 to %3, step %4) : tile<i32> iter_values(%7 = %1) -> (tile<128x128xf32>) {
      %8 = assume div_by<16>, %arg0 : tile<ptr<bf16>>
      %9 = make_tensor_view %8, shape = [301, 299], strides = [299, 1] : tensor_view<301x299xbf16, strides=[299, 1]>
      %10 = make_partition_view %9 : partition_view<tile=(128x64), padding_value = zero, tensor_view<301x299xbf16, strides=[299, 1]>, dim_map=[0, 1]>
      %11, %12, %13 = get_tile_block_id : tile<i32>
      %14, %15 = load_view_tko weak %10[%11, %6] token=%0 : partition_view<tile=(128x64), padding_value = zero, tensor_view<301x299xbf16, strides=[299, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<128x64xbf16>, token
      %16 = assume div_by<16>, %arg1 : tile<ptr<bf16>>
      %17 = make_tensor_view %16, shape = [299, 203], strides = [203, 1] : tensor_view<299x203xbf16, strides=[203, 1]>
      %18 = make_partition_view %17 : partition_view<tile=(64x128), padding_value = zero, tensor_view<299x203xbf16, strides=[203, 1]>, dim_map=[0, 1]>
      %19, %20, %21 = get_tile_block_id : tile<i32>
      %22, %23 = load_view_tko weak %18[%6, %20] token=%0 : partition_view<tile=(64x128), padding_value = zero, tensor_view<299x203xbf16, strides=[203, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x128xbf16>, token
      %24 = mmaf %14, %22, %7 : tile<128x64xbf16>, tile<64x128xbf16>, tile<128x128xf32>
      continue %24 : tile<128x128xf32>
    }
    %25 = assume div_by<16>, %arg2 : tile<ptr<f32>>
    %26 = make_tensor_view %25, shape = [301, 203], strides = [203, 1] : tensor_view<301x203xf32, strides=[203, 1]>
    %27 = make_partition_view %26 : partition_view<tile=(128x128), padding_value = zero, tensor_view<301x203xf32, strides=[203, 1]>, dim_map=[0, 1]>
    %28, %29, %30 = get_tile_block_id : tile<i32>
    %31, %32, %33 = get_tile_block_id : tile<i32>
    %34 = store_view_tko weak %5, %27[%28, %32] token=%0 : tile<128x128xf32>, partition_view<tile=(128x128), padding_value = zero, tensor_view<301x203xf32, strides=[203, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
