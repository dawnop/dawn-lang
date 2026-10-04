cuda_tile.module @m {
  entry @silu(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %9 = negf %7 : tile<1024xf64>
    %10 = exp %9 : tile<1024xf64>
    %11 = constant <f64: 1.0> : tile<1024xf64>
    %12 = addf %11, %10 rounding<nearest_even> : tile<1024xf64>
    %13 = divf %7, %12 rounding<nearest_even> : tile<1024xf64>
    %14 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %15 = make_tensor_view %14, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %17 = store_view_tko weak %13, %16[%4] token=%8 : tile<1024xf64>, partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
