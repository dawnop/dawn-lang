cuda_tile.module @m {
  entry @swiglu_proj(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<32x32xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 2> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5, %6 = for %7 in (%2 to %3, step %4) : tile<i32> iter_values(%8 = %1, %9 = %0) -> (tile<32x32xf64>, token) {
      %10 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %11 = make_tensor_view %10, shape = [32, 64], strides = [64, 1] : tensor_view<32x64xf64, strides=[64, 1]>
      %12 = make_partition_view %11 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %13, %14, %15 = get_tile_block_id : tile<i32>
      %16, %17 = load_view_tko weak %12[%13, %7] token=%9 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %18 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %19 = make_tensor_view %18, shape = [64, 128], strides = [128, 1] : tensor_view<64x128xf64, strides=[128, 1]>
      %20 = make_partition_view %19 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>
      %21, %22, %23 = get_tile_block_id : tile<i32>
      %24, %25 = load_view_tko weak %20[%7, %22] token=%17 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %26 = mmaf %16, %24, %8 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %26, %25 : tile<32x32xf64>, token
    }
    %27 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %28 = make_tensor_view %27, shape = [32, 128], strides = [128, 1] : tensor_view<32x128xf64, strides=[128, 1]>
    %29 = make_partition_view %28 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x128xf64, strides=[128, 1]>, dim_map=[0, 1]>
    %30, %31, %32 = get_tile_block_id : tile<i32>
    %33, %34, %35 = get_tile_block_id : tile<i32>
    %36 = store_view_tko weak %5, %29[%30, %34] token=%6 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<32x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
