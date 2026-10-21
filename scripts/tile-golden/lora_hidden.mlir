cuda_tile.module @m {
  entry @lora_hidden(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<32x16xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 2> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5 = for %6 in (%2 to %3, step %4) : tile<i32> iter_values(%7 = %1) -> (tile<32x16xf64>) {
      %8 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %9 = make_tensor_view %8, shape = [32, 64], strides = [64, 1] : tensor_view<32x64xf64, strides=[64, 1]>
      %10 = make_partition_view %9 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %11, %12, %13 = get_tile_block_id : tile<i32>
      %14, %15 = load_view_tko weak %10[%11, %6] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %16 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %17 = make_tensor_view %16, shape = [16, 64], strides = [64, 1] : tensor_view<16x64xf64, strides=[64, 1]>
      %18 = make_partition_view %17 : partition_view<tile=(16x32), padding_value = zero, tensor_view<16x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %19, %20 = load_view_tko weak %18[%11, %6] token=%0 : partition_view<tile=(16x32), padding_value = zero, tensor_view<16x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x32xf64>, token
      %21 = permute %19 [1, 0] : tile<16x32xf64> -> tile<32x16xf64>
      %22 = mmaf %14, %21, %7 : tile<32x32xf64>, tile<32x16xf64>, tile<32x16xf64>
      continue %22 : tile<32x16xf64>
    }
    %23 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %24 = make_tensor_view %23, shape = [32, 16], strides = [16, 1] : tensor_view<32x16xf64, strides=[16, 1]>
    %25 = make_partition_view %24 : partition_view<tile=(32x16), padding_value = zero, tensor_view<32x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %26, %27, %28 = get_tile_block_id : tile<i32>
    %29, %30, %31 = get_tile_block_id : tile<i32>
    %32 = store_view_tko weak %5, %25[%26, %30] token=%0 : tile<32x16xf64>, partition_view<tile=(32x16), padding_value = zero, tensor_view<32x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
