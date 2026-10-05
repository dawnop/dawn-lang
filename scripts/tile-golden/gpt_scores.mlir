cuda_tile.module @m {
  entry @gpt_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %5 = make_tensor_view %4, shape = [64, 192], strides = [192, 1] : tensor_view<64x192xf64, strides=[192, 1]>
    %6 = make_partition_view %5 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x192xf64, strides=[192, 1]>, dim_map=[0, 1]>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %6[%7, %3] token=%0 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x192xf64, strides=[192, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
    %12 = constant <i32: 2> : tile<i32>
    %13 = addi %12, %3 : tile<i32>
    %14, %15 = load_view_tko weak %6[%7, %13] token=%11 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x192xf64, strides=[192, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
    %16 = permute %14 [1, 0] : tile<64x32xf64> -> tile<32x64xf64>
    %17 = constant <f64: 0.0> : tile<64x64xf64>
    %18 = mmaf %10, %16, %17 : tile<64x32xf64>, tile<32x64xf64>, tile<64x64xf64>
    %19 = constant <f64: 0.17677669529663687> : tile<64x64xf64>
    %20 = mulf %18, %19 rounding<nearest_even> : tile<64x64xf64>
    %21 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %22 = make_tensor_view %21, shape = [128, 64], strides = [64, 1] : tensor_view<128x64xf64, strides=[64, 1]>
    %23 = make_partition_view %22 : partition_view<tile=(64x64), padding_value = zero, tensor_view<128x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %24, %25, %26 = get_tile_block_id : tile<i32>
    %27 = store_view_tko weak %20, %23[%26, %7] token=%15 : tile<64x64xf64>, partition_view<tile=(64x64), padding_value = zero, tensor_view<128x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
