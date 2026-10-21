cuda_tile.module @m {
  entry @gpt_context(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 4> : tile<i32>
    %2, %3, %4 = get_tile_block_id : tile<i32>
    %5 = addi %1, %4 : tile<i32>
    %6 = constant <f64: 0.0> : tile<64x32xf64>
    %7 = constant <i32: 0> : tile<i32>
    %8 = constant <i32: 2> : tile<i32>
    %9 = constant <i32: 1> : tile<i32>
    %10 = for %11 in (%7 to %8, step %9) : tile<i32> iter_values(%12 = %6) -> (tile<64x32xf64>) {
      %13 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %14 = make_tensor_view %13, shape = [128, 64], strides = [64, 1] : tensor_view<128x64xf64, strides=[64, 1]>
      %15 = make_partition_view %14 : partition_view<tile=(64x32), padding_value = zero, tensor_view<128x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %16, %17, %18 = get_tile_block_id : tile<i32>
      %19, %20 = load_view_tko weak %15[%18, %11] token=%0 : partition_view<tile=(64x32), padding_value = zero, tensor_view<128x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
      %21 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %22 = make_tensor_view %21, shape = [64, 192], strides = [192, 1] : tensor_view<64x192xf64, strides=[192, 1]>
      %23 = make_partition_view %22 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x192xf64, strides=[192, 1]>, dim_map=[0, 1]>
      %24, %25 = load_view_tko weak %23[%11, %5] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x192xf64, strides=[192, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %26 = mmaf %19, %24, %12 : tile<64x32xf64>, tile<32x32xf64>, tile<64x32xf64>
      continue %26 : tile<64x32xf64>
    }
    %27 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %28 = make_tensor_view %27, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %29 = make_partition_view %28 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %30, %31, %32 = get_tile_block_id : tile<i32>
    %33, %34, %35 = get_tile_block_id : tile<i32>
    %36 = store_view_tko weak %10, %29[%30, %35] token=%0 : tile<64x32xf64>, partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
