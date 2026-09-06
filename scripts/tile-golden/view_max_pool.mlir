cuda_tile.module @m {
  entry @view_max_pool(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <f64: -Infinity> : tile<16x16xf64>
    %8 = constant <i32: 0> : tile<i32>
    %9 = offset %arg0, %8 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %10 = make_tensor_view %9, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %11 = make_partition_view %10 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %12, %13 = load_view_tko weak %11[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %14 = maxf %7, %12 : tile<16x16xf64>
    %15 = constant <i32: 1> : tile<i32>
    %16 = offset %arg0, %15 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %17 = make_tensor_view %16, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %18 = make_partition_view %17 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %19, %20 = load_view_tko weak %18[%1, %5] token=%13 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %21 = maxf %14, %19 : tile<16x16xf64>
    %22 = constant <i32: 20> : tile<i32>
    %23 = offset %arg0, %22 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %24 = make_tensor_view %23, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %25 = make_partition_view %24 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %26, %27 = load_view_tko weak %25[%1, %5] token=%20 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %28 = maxf %21, %26 : tile<16x16xf64>
    %29 = constant <i32: 21> : tile<i32>
    %30 = offset %arg0, %29 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %31 = make_tensor_view %30, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %32 = make_partition_view %31 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %33, %34 = load_view_tko weak %32[%1, %5] token=%27 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %35 = maxf %28, %33 : tile<16x16xf64>
    %36 = constant <i32: 0> : tile<i32>
    %37 = offset %arg1, %36 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %38 = make_tensor_view %37, shape = [18, 10], strides = [10, 1] : tensor_view<18x10xf64, strides=[10, 1]>
    %39 = make_partition_view %38 : partition_view<tile=(16x16), tensor_view<18x10xf64, strides=[10, 1]>, dim_map=[0, 1]>
    %40 = store_view_tko weak %35, %39[%1, %5] token=%34 : tile<16x16xf64>, partition_view<tile=(16x16), tensor_view<18x10xf64, strides=[10, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
