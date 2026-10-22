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
    %11 = constant <i32: 15> : tile<i32>
    %12 = constant <i32: 31> : tile<i32>
    %13 = andi %11, %12 : tile<i32>
    %14 = reshape %13 : tile<i32> -> tile<1xi32>
    %15 = broadcast %14 : tile<1xi32> -> tile<128xi32>
    %16 = shri %10, %15 unsigned : tile<128xi32>
    %17 = xori %10, %16 : tile<128xi32>
    %18 = constant <i32: 2135587861> : tile<128xi32>
    %19 = addi %17, %18 : tile<128xi32>
    %20 = constant <i32: 13> : tile<i32>
    %21 = constant <i32: 31> : tile<i32>
    %22 = andi %20, %21 : tile<i32>
    %23 = reshape %22 : tile<i32> -> tile<1xi32>
    %24 = broadcast %23 : tile<1xi32> -> tile<128xi32>
    %25 = shri %19, %24 signed : tile<128xi32>
    %26 = xori %19, %25 : tile<128xi32>
    %27 = constant <i32: -2048144777> : tile<128xi32>
    %28 = muli %26, %27 : tile<128xi32>
    %29 = constant <i32: 16> : tile<i32>
    %30 = constant <i32: 31> : tile<i32>
    %31 = andi %29, %30 : tile<i32>
    %32 = reshape %31 : tile<i32> -> tile<1xi32>
    %33 = broadcast %32 : tile<1xi32> -> tile<128xi32>
    %34 = shri %28, %33 unsigned : tile<128xi32>
    %35 = xori %28, %34 : tile<128xi32>
    %36 = constant <i32: -1640531535> : tile<128xi32>
    %37 = muli %35, %36 : tile<128xi32>
    %38 = constant <i32: 15> : tile<i32>
    %39 = constant <i32: 31> : tile<i32>
    %40 = andi %38, %39 : tile<i32>
    %41 = reshape %40 : tile<i32> -> tile<1xi32>
    %42 = broadcast %41 : tile<1xi32> -> tile<128xi32>
    %43 = shri %37, %42 unsigned : tile<128xi32>
    %44 = xori %37, %43 : tile<128xi32>
    %45 = constant <i32: 2135587861> : tile<128xi32>
    %46 = addi %44, %45 : tile<128xi32>
    %47 = constant <i32: 13> : tile<i32>
    %48 = constant <i32: 31> : tile<i32>
    %49 = andi %47, %48 : tile<i32>
    %50 = reshape %49 : tile<i32> -> tile<1xi32>
    %51 = broadcast %50 : tile<1xi32> -> tile<128xi32>
    %52 = shri %46, %51 signed : tile<128xi32>
    %53 = xori %46, %52 : tile<128xi32>
    %54 = constant <i32: -2048144777> : tile<128xi32>
    %55 = muli %53, %54 : tile<128xi32>
    %56 = constant <i32: 16> : tile<i32>
    %57 = constant <i32: 31> : tile<i32>
    %58 = andi %56, %57 : tile<i32>
    %59 = reshape %58 : tile<i32> -> tile<1xi32>
    %60 = broadcast %59 : tile<1xi32> -> tile<128xi32>
    %61 = shri %55, %60 unsigned : tile<128xi32>
    %62 = xori %55, %61 : tile<128xi32>
    %63 = constant <i32: -1640531535> : tile<128xi32>
    %64 = muli %62, %63 : tile<128xi32>
    %65 = constant <i32: 15> : tile<i32>
    %66 = constant <i32: 31> : tile<i32>
    %67 = andi %65, %66 : tile<i32>
    %68 = reshape %67 : tile<i32> -> tile<1xi32>
    %69 = broadcast %68 : tile<1xi32> -> tile<128xi32>
    %70 = shri %64, %69 unsigned : tile<128xi32>
    %71 = xori %64, %70 : tile<128xi32>
    %72 = constant <i32: 2135587861> : tile<128xi32>
    %73 = addi %71, %72 : tile<128xi32>
    %74 = constant <i32: 13> : tile<i32>
    %75 = constant <i32: 31> : tile<i32>
    %76 = andi %74, %75 : tile<i32>
    %77 = reshape %76 : tile<i32> -> tile<1xi32>
    %78 = broadcast %77 : tile<1xi32> -> tile<128xi32>
    %79 = shri %73, %78 signed : tile<128xi32>
    %80 = xori %73, %79 : tile<128xi32>
    %81 = constant <i32: -2048144777> : tile<128xi32>
    %82 = muli %80, %81 : tile<128xi32>
    %83 = constant <i32: 16> : tile<i32>
    %84 = constant <i32: 31> : tile<i32>
    %85 = andi %83, %84 : tile<i32>
    %86 = reshape %85 : tile<i32> -> tile<1xi32>
    %87 = broadcast %86 : tile<1xi32> -> tile<128xi32>
    %88 = shri %82, %87 unsigned : tile<128xi32>
    %89 = xori %82, %88 : tile<128xi32>
    %90 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %91 = make_tensor_view %90, shape = [1000], strides = [1] : tensor_view<1000xi32, strides=[1]>
    %92 = make_partition_view %91 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>
    %93 = store_view_tko weak %89, %92[%4] token=%0 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
