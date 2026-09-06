cuda_tile.module @m {
  entry @view_padding(%arg0: tile<ptr<f32>>, %arg1: tile<ptr<f32>>, %arg2: tile<ptr<f32>>, %arg3: tile<ptr<f32>>, %arg4: tile<ptr<f32>>, %arg5: tile<ptr<f32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_tile_block_id : tile<i32>
    %5 = offset %arg0, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %6 = make_tensor_view %5, shape = [100], strides = [1] : tensor_view<100xf32, strides=[1]>
    %7 = make_partition_view %6 : partition_view<tile=(32), padding_value = zero, tensor_view<100xf32, strides=[1]>, dim_map=[0]>
    %8 = offset %arg1, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %9 = make_tensor_view %8, shape = [128], strides = [1] : tensor_view<128xf32, strides=[1]>
    %10 = make_partition_view %9 : partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>
    %11, %12 = load_view_tko weak %7[%2] token=%0 : partition_view<tile=(32), padding_value = zero, tensor_view<100xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf32>, token
    %13 = store_view_tko weak %11, %10[%2] token=%12 : tile<32xf32>, partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %14 = make_partition_view %6 : partition_view<tile=(32), padding_value = neg_zero, tensor_view<100xf32, strides=[1]>, dim_map=[0]>
    %15 = offset %arg2, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %16 = make_tensor_view %15, shape = [128], strides = [1] : tensor_view<128xf32, strides=[1]>
    %17 = make_partition_view %16 : partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>
    %18, %19 = load_view_tko weak %14[%2] token=%13 : partition_view<tile=(32), padding_value = neg_zero, tensor_view<100xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf32>, token
    %20 = store_view_tko weak %18, %17[%2] token=%19 : tile<32xf32>, partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %21 = make_partition_view %6 : partition_view<tile=(32), padding_value = nan, tensor_view<100xf32, strides=[1]>, dim_map=[0]>
    %22 = offset %arg3, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %23 = make_tensor_view %22, shape = [128], strides = [1] : tensor_view<128xf32, strides=[1]>
    %24 = make_partition_view %23 : partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>
    %25, %26 = load_view_tko weak %21[%2] token=%20 : partition_view<tile=(32), padding_value = nan, tensor_view<100xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf32>, token
    %27 = store_view_tko weak %25, %24[%2] token=%26 : tile<32xf32>, partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %28 = make_partition_view %6 : partition_view<tile=(32), padding_value = pos_inf, tensor_view<100xf32, strides=[1]>, dim_map=[0]>
    %29 = offset %arg4, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %30 = make_tensor_view %29, shape = [128], strides = [1] : tensor_view<128xf32, strides=[1]>
    %31 = make_partition_view %30 : partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>
    %32, %33 = load_view_tko weak %28[%2] token=%27 : partition_view<tile=(32), padding_value = pos_inf, tensor_view<100xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf32>, token
    %34 = store_view_tko weak %32, %31[%2] token=%33 : tile<32xf32>, partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %35 = make_partition_view %6 : partition_view<tile=(32), padding_value = neg_inf, tensor_view<100xf32, strides=[1]>, dim_map=[0]>
    %36 = offset %arg5, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %37 = make_tensor_view %36, shape = [128], strides = [1] : tensor_view<128xf32, strides=[1]>
    %38 = make_partition_view %37 : partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>
    %39, %40 = load_view_tko weak %35[%2] token=%34 : partition_view<tile=(32), padding_value = neg_inf, tensor_view<100xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf32>, token
    %41 = store_view_tko weak %39, %38[%2] token=%40 : tile<32xf32>, partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
