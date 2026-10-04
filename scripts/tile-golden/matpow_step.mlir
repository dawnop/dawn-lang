cuda_tile.module @m {
  entry @matpow_step(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [32, 32], strides = [32, 1] : tensor_view<32x32xf64, strides=[32, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %3[%4, %8] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %12 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %13 = make_tensor_view %12, shape = [32, 32], strides = [32, 1] : tensor_view<32x32xf64, strides=[32, 1]>
    %14 = make_partition_view %13 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %15, %16 = load_view_tko weak %14[%4, %8] token=%11 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %17 = constant <f64: 0.0> : tile<32x32xf64>
    %18 = mmaf %10, %15, %17 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %19 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %20 = make_tensor_view %19, shape = [32, 32], strides = [32, 1] : tensor_view<32x32xf64, strides=[32, 1]>
    %21 = make_partition_view %20 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %22 = store_view_tko weak %18, %21[%4, %8] token=%16 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
