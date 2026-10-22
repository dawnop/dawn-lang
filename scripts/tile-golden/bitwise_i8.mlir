cuda_tile.module @m {
  entry @bitwise_i8(%arg0: tile<ptr<i8>>, %arg1: tile<ptr<i8>>, %arg2: tile<ptr<i8>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i8>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xi8, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi8, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi8, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi8>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<i8>>
    %10 = make_tensor_view %9, shape = [512], strides = [1] : tensor_view<512xi8, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi8, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi8, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi8>, token
    %14 = andi %7, %12 : tile<128xi8>
    %15 = reshape %14 : tile<128xi8> -> tile<1x128xi8>
    %16 = assume div_by<16>, %arg2 : tile<ptr<i8>>
    %17 = make_tensor_view %16, shape = [4, 512], strides = [512, 1] : tensor_view<4x512xi8, strides=[512, 1]>
    %18 = make_partition_view %17 : partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xi8, strides=[512, 1]>, dim_map=[0, 1]>
    %19, %20, %21 = get_tile_block_id : tile<i32>
    %22 = constant <i32: 4> : tile<i32>
    %23 = muli %20, %22 : tile<i32>
    %24 = store_view_tko weak %15, %18[%23, %4] token=%0 : tile<1x128xi8>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xi8, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %25 = ori %7, %12 : tile<128xi8>
    %26 = reshape %25 : tile<128xi8> -> tile<1x128xi8>
    %27 = constant <i32: 4> : tile<i32>
    %28 = muli %20, %27 : tile<i32>
    %29 = constant <i32: 1> : tile<i32>
    %30 = addi %28, %29 : tile<i32>
    %31 = store_view_tko weak %26, %18[%30, %4] token=%24 : tile<1x128xi8>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xi8, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %32 = xori %7, %12 : tile<128xi8>
    %33 = reshape %32 : tile<128xi8> -> tile<1x128xi8>
    %34 = constant <i32: 4> : tile<i32>
    %35 = muli %20, %34 : tile<i32>
    %36 = constant <i32: 2> : tile<i32>
    %37 = addi %35, %36 : tile<i32>
    %38 = store_view_tko weak %33, %18[%37, %4] token=%31 : tile<1x128xi8>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xi8, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %39 = constant <i8: -1> : tile<128xi8>
    %40 = xori %7, %39 : tile<128xi8>
    %41 = reshape %40 : tile<128xi8> -> tile<1x128xi8>
    %42 = constant <i32: 4> : tile<i32>
    %43 = muli %20, %42 : tile<i32>
    %44 = constant <i32: 3> : tile<i32>
    %45 = addi %43, %44 : tile<i32>
    %46 = store_view_tko weak %41, %18[%45, %4] token=%38 : tile<1x128xi8>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xi8, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
