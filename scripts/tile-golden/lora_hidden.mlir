cuda_tile.module @m {
  entry @lora_hidden(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<32x16xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 2> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5, %6 = for %7 in (%2 to %3, step %4) : tile<i32> iter_values(%8 = %1, %9 = %0) -> (tile<32x16xf64>, token) {
      %10 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %11 = make_tensor_view %10, shape = [32, 64], strides = [64, 1] : tensor_view<32x64xf64, strides=[64, 1]>
      %12 = make_partition_view %11 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %13, %14, %15 = get_tile_block_id : tile<i32>
      %16, %17 = load_view_tko weak %12[%13, %7] token=%9 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %18 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %19 = make_tensor_view %18, shape = [16, 64], strides = [64, 1] : tensor_view<16x64xf64, strides=[64, 1]>
      %20 = make_partition_view %19 : partition_view<tile=(16x32), padding_value = zero, tensor_view<16x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %21, %22 = load_view_tko weak %20[%13, %7] token=%17 : partition_view<tile=(16x32), padding_value = zero, tensor_view<16x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x32xf64>, token
      %23 = permute %21 [1, 0] : tile<16x32xf64> -> tile<32x16xf64>
      %24 = mmaf %16, %23, %8 : tile<32x32xf64>, tile<32x16xf64>, tile<32x16xf64>
      continue %24, %22 : tile<32x16xf64>, token
    }
    %25 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %26 = make_tensor_view %25, shape = [32, 16], strides = [16, 1] : tensor_view<32x16xf64, strides=[16, 1]>
    %27 = make_partition_view %26 : partition_view<tile=(32x16), padding_value = zero, tensor_view<32x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %28, %29, %30 = get_tile_block_id : tile<i32>
    %31, %32, %33 = get_tile_block_id : tile<i32>
    %34 = store_view_tko weak %5, %27[%28, %32] token=%6 : tile<32x16xf64>, partition_view<tile=(32x16), padding_value = zero, tensor_view<32x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
