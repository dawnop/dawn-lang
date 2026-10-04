cuda_tile.module @m {
  entry @rainbow(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %9 = constant <i32: -1640531535> : tile<128xi32>
    %10 = muli %7, %9 : tile<128xi32>
    %11 = constant <i32: 15> : tile<128xi32>
    %12 = shri %10, %11 unsigned : tile<128xi32>
    %13 = xori %10, %12 : tile<128xi32>
    %14 = constant <i32: 2135587861> : tile<128xi32>
    %15 = addi %13, %14 : tile<128xi32>
    %16 = constant <i32: 13> : tile<128xi32>
    %17 = shri %15, %16 signed : tile<128xi32>
    %18 = xori %15, %17 : tile<128xi32>
    %19 = constant <i32: -2048144777> : tile<128xi32>
    %20 = muli %18, %19 : tile<128xi32>
    %21 = constant <i32: 16> : tile<128xi32>
    %22 = shri %20, %21 unsigned : tile<128xi32>
    %23 = xori %20, %22 : tile<128xi32>
    %24 = constant <i32: -1640531535> : tile<128xi32>
    %25 = muli %23, %24 : tile<128xi32>
    %26 = constant <i32: 15> : tile<128xi32>
    %27 = shri %25, %26 unsigned : tile<128xi32>
    %28 = xori %25, %27 : tile<128xi32>
    %29 = constant <i32: 2135587861> : tile<128xi32>
    %30 = addi %28, %29 : tile<128xi32>
    %31 = constant <i32: 13> : tile<128xi32>
    %32 = shri %30, %31 signed : tile<128xi32>
    %33 = xori %30, %32 : tile<128xi32>
    %34 = constant <i32: -2048144777> : tile<128xi32>
    %35 = muli %33, %34 : tile<128xi32>
    %36 = constant <i32: 16> : tile<128xi32>
    %37 = shri %35, %36 unsigned : tile<128xi32>
    %38 = xori %35, %37 : tile<128xi32>
    %39 = constant <i32: -1640531535> : tile<128xi32>
    %40 = muli %38, %39 : tile<128xi32>
    %41 = constant <i32: 15> : tile<128xi32>
    %42 = shri %40, %41 unsigned : tile<128xi32>
    %43 = xori %40, %42 : tile<128xi32>
    %44 = constant <i32: 2135587861> : tile<128xi32>
    %45 = addi %43, %44 : tile<128xi32>
    %46 = constant <i32: 13> : tile<128xi32>
    %47 = shri %45, %46 signed : tile<128xi32>
    %48 = xori %45, %47 : tile<128xi32>
    %49 = constant <i32: -2048144777> : tile<128xi32>
    %50 = muli %48, %49 : tile<128xi32>
    %51 = constant <i32: 16> : tile<128xi32>
    %52 = shri %50, %51 unsigned : tile<128xi32>
    %53 = xori %50, %52 : tile<128xi32>
    %54 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %55 = make_tensor_view %54, shape = [1000], strides = [1] : tensor_view<1000xi32, strides=[1]>
    %56 = make_partition_view %55 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>
    %57 = store_view_tko weak %53, %56[%4] token=%8 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
