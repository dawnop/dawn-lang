cuda_tile.module @m {
  entry @attn_bwd_mmt(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<32x32xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 2> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5, %6 = for %7 in (%2 to %3, step %4) : tile<i32> iter_values(%8 = %1, %9 = %0) -> (tile<32x32xf64>, token) {
      %10 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %11 = make_tensor_view %10, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
      %12 = make_partition_view %11 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %13, %14, %15 = get_tile_block_id : tile<i32>
      %16, %17 = load_view_tko weak %12[%7, %13] token=%9 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %18 = permute %16 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
      %19 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %20 = make_tensor_view %19, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
      %21 = make_partition_view %20 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
      %22, %23, %24 = get_tile_block_id : tile<i32>
      %25, %26 = load_view_tko weak %21[%7, %23] token=%17 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %27 = mmaf %18, %25, %8 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %27, %26 : tile<32x32xf64>, token
    }
    %28 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %29 = make_tensor_view %28, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %30 = make_partition_view %29 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %31, %32, %33 = get_tile_block_id : tile<i32>
    %34, %35, %36 = get_tile_block_id : tile<i32>
    %37 = store_view_tko weak %5, %30[%31, %35] token=%6 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
