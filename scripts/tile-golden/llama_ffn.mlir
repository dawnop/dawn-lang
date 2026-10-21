cuda_tile.module @m {
  entry @llama_ffn(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<64x32xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 4> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5 = for %6 in (%2 to %3, step %4) : tile<i32> iter_values(%7 = %1) -> (tile<64x32xf64>) {
      %8 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %9 = make_tensor_view %8, shape = [64, 128], strides = [128, 1] : tensor_view<64x128xf64, strides=[128, 1]>
      %10 = make_partition_view %9 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>
      %11, %12, %13 = get_tile_block_id : tile<i32>
      %14, %15 = load_view_tko weak %10[%11, %6] token=%0 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
      %16 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %17 = make_tensor_view %16, shape = [64, 128], strides = [128, 1] : tensor_view<64x128xf64, strides=[128, 1]>
      %18 = make_partition_view %17 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>
      %19, %20, %21 = get_tile_block_id : tile<i32>
      %22, %23 = load_view_tko weak %18[%20, %6] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %24 = permute %22 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
      %25 = mmaf %14, %24, %7 : tile<64x32xf64>, tile<32x32xf64>, tile<64x32xf64>
      continue %25 : tile<64x32xf64>
    }
    %26 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %27 = make_tensor_view %26, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %28 = make_partition_view %27 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %29, %30, %31 = get_tile_block_id : tile<i32>
    %32, %33, %34 = get_tile_block_id : tile<i32>
    %35 = store_view_tko weak %5, %28[%29, %33] token=%0 : tile<64x32xf64>, partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
