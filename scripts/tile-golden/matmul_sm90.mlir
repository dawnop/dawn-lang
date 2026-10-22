cuda_tile.module @m {
  entry @matmul_sm90(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) optimization_hints=<sm_90 = {occupancy = 2}> {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<16x64xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 16> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5 = for %6 in (%2 to %3, step %4) : tile<i32> iter_values(%7 = %1) -> (tile<16x64xf64>) {
      %8 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %9 = make_tensor_view %8, shape = [256, 256], strides = [256, 1] : tensor_view<256x256xf64, strides=[256, 1]>
      %10 = make_partition_view %9 : partition_view<tile=(16x16), padding_value = zero, tensor_view<256x256xf64, strides=[256, 1]>, dim_map=[0, 1]>
      %11, %12, %13 = get_tile_block_id : tile<i32>
      %14, %15 = load_view_tko weak %10[%11, %6] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<256x256xf64, strides=[256, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
      %16 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %17 = make_tensor_view %16, shape = [256, 256], strides = [256, 1] : tensor_view<256x256xf64, strides=[256, 1]>
      %18 = make_partition_view %17 : partition_view<tile=(16x64), padding_value = zero, tensor_view<256x256xf64, strides=[256, 1]>, dim_map=[0, 1]>
      %19, %20, %21 = get_tile_block_id : tile<i32>
      %22, %23 = load_view_tko weak %18[%6, %20] token=%0 : partition_view<tile=(16x64), padding_value = zero, tensor_view<256x256xf64, strides=[256, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x64xf64>, token
      %24 = mmaf %14, %22, %7 : tile<16x16xf64>, tile<16x64xf64>, tile<16x64xf64>
      continue %24 : tile<16x64xf64>
    }
    %25 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %26 = make_tensor_view %25, shape = [256, 256], strides = [256, 1] : tensor_view<256x256xf64, strides=[256, 1]>
    %27 = make_partition_view %26 : partition_view<tile=(16x64), padding_value = zero, tensor_view<256x256xf64, strides=[256, 1]>, dim_map=[0, 1]>
    %28, %29, %30 = get_tile_block_id : tile<i32>
    %31, %32, %33 = get_tile_block_id : tile<i32>
    %34 = store_view_tko weak %5, %27[%28, %32] token=%0 : tile<16x64xf64>, partition_view<tile=(16x64), padding_value = zero, tensor_view<256x256xf64, strides=[256, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
