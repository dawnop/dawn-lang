cuda_tile.module @m {
  entry @attn_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %3 = make_tensor_view %2, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %4 = make_partition_view %3 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %5, %6, %7 = get_tile_block_id : tile<i32>
    %8, %9 = load_view_tko weak %4[%5, %1] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %10 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %11 = make_tensor_view %10, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %12 = make_partition_view %11 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %13, %14, %15 = get_tile_block_id : tile<i32>
    %16, %17 = load_view_tko weak %12[%14, %1] token=%9 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %18 = permute %16 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
    %19 = constant <f64: 0.0> : tile<32x32xf64>
    %20 = mmaf %8, %18, %19 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %21 = constant <f64: 0.17677669529663687> : tile<32x32xf64>
    %22 = mulf %20, %21 rounding<nearest_even> : tile<32x32xf64>
    %23 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %24 = make_tensor_view %23, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %25 = make_partition_view %24 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %26 = store_view_tko weak %22, %25[%5, %14] token=%17 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
