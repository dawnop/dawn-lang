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
    %10, %11 = for %12 in (%7 to %8, step %9) : tile<i32> iter_values(%13 = %6, %14 = %0) -> (tile<64x32xf64>, token) {
      %15 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %16 = make_tensor_view %15, shape = [128, 64], strides = [64, 1] : tensor_view<128x64xf64, strides=[64, 1]>
      %17 = make_partition_view %16 : partition_view<tile=(64x32), padding_value = zero, tensor_view<128x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %18, %19, %20 = get_tile_block_id : tile<i32>
      %21, %22 = load_view_tko weak %17[%20, %12] token=%14 : partition_view<tile=(64x32), padding_value = zero, tensor_view<128x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
      %23 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %24 = make_tensor_view %23, shape = [64, 192], strides = [192, 1] : tensor_view<64x192xf64, strides=[192, 1]>
      %25 = make_partition_view %24 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x192xf64, strides=[192, 1]>, dim_map=[0, 1]>
      %26, %27 = load_view_tko weak %25[%12, %5] token=%22 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x192xf64, strides=[192, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %28 = mmaf %21, %26, %13 : tile<64x32xf64>, tile<32x32xf64>, tile<64x32xf64>
      continue %28, %27 : tile<64x32xf64>, token
    }
    %29 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %30 = make_tensor_view %29, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %31 = make_partition_view %30 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %32, %33, %34 = get_tile_block_id : tile<i32>
    %35, %36, %37 = get_tile_block_id : tile<i32>
    %38 = store_view_tko weak %10, %31[%32, %37] token=%11 : tile<64x32xf64>, partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
