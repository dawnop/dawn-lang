cuda_tile.module @m {
  entry @lora_out(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %3 = make_tensor_view %2, shape = [32, 16], strides = [16, 1] : tensor_view<32x16xf64, strides=[16, 1]>
    %4 = make_partition_view %3 : partition_view<tile=(32x16), padding_value = zero, tensor_view<32x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %5, %6, %7 = get_tile_block_id : tile<i32>
    %8, %9 = load_view_tko weak %4[%5, %1] token=%0 : partition_view<tile=(32x16), padding_value = zero, tensor_view<32x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x16xf64>, token
    %10 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %11 = make_tensor_view %10, shape = [64, 16], strides = [16, 1] : tensor_view<64x16xf64, strides=[16, 1]>
    %12 = make_partition_view %11 : partition_view<tile=(32x16), padding_value = zero, tensor_view<64x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %13, %14, %15 = get_tile_block_id : tile<i32>
    %16, %17 = load_view_tko weak %12[%14, %1] token=%9 : partition_view<tile=(32x16), padding_value = zero, tensor_view<64x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x16xf64>, token
    %18 = permute %16 [1, 0] : tile<32x16xf64> -> tile<16x32xf64>
    %19 = constant <f64: 0.0> : tile<32x32xf64>
    %20 = mmaf %8, %18, %19 : tile<32x16xf64>, tile<16x32xf64>, tile<32x32xf64>
    %21 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %22 = make_tensor_view %21, shape = [32, 64], strides = [64, 1] : tensor_view<32x64xf64, strides=[64, 1]>
    %23 = make_partition_view %22 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %24, %25 = load_view_tko weak %23[%5, %14] token=%17 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %26 = constant <f64: 0.5> : tile<32x32xf64>
    %27 = mulf %26, %20 rounding<nearest_even> : tile<32x32xf64>
    %28 = addf %24, %27 rounding<nearest_even> : tile<32x32xf64>
    %29 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %30 = make_tensor_view %29, shape = [32, 64], strides = [64, 1] : tensor_view<32x64xf64, strides=[64, 1]>
    %31 = make_partition_view %30 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %32 = store_view_tko weak %28, %31[%5, %14] token=%25 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
