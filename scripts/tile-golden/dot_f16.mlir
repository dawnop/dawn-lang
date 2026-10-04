cuda_tile.module @m {
  entry @dot_f16(%arg0: tile<ptr<f16>>, %arg1: tile<ptr<f16>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f16>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf16, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf16, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf16, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf16>, token
    %9 = ftof %7 rounding<nearest_even> : tile<1024xf16> -> tile<1024xf64>
    %10 = assume div_by<16>, %arg1 : tile<ptr<f16>>
    %11 = make_tensor_view %10, shape = [1000], strides = [1] : tensor_view<1000xf16, strides=[1]>
    %12 = make_partition_view %11 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf16, strides=[1]>, dim_map=[0]>
    %13, %14 = load_view_tko weak %12[%4] token=%8 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf16, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf16>, token
    %15 = ftof %13 rounding<nearest_even> : tile<1024xf16> -> tile<1024xf64>
    %16 = mulf %9, %15 rounding<nearest_even> : tile<1024xf64>
    %17 = reduce %16 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%18: tile<f64>, %19: tile<f64>) {
      %20 = addf %18, %19 rounding<nearest_even> : tile<f64>
      yield %20 : tile<f64>
    }
    %21 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %22 = make_tensor_view %21, shape = [1], strides = [1] : tensor_view<1xf64, strides=[1]>
    %23 = make_partition_view %22 : partition_view<tile=(1), padding_value = zero, tensor_view<1xf64, strides=[1]>, dim_map=[0]>
    %24 = reshape %17 : tile<f64> -> tile<1xf64>
    %25 = broadcast %24 : tile<1xf64> -> tile<1xf64>
    %26 = store_view_tko weak %25, %23[%4] token=%14 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<1xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
